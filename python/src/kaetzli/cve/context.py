"""test/cve-scan.py's findings with what the rest of the world knows about each, so a
triage starts from more than NVD's severity and a CPE match:

    ./test/cve-context.py                 # output/cve/*.json, or CI's newest scan on main
    RUN=<id> ARCH=arm64 ./test/cve-context.py   # that run's scan, for that arch
    ./test/cve-context.py <dir>           # <dir>/cve/*.json, e.g. a cve-<arch> artifact
    OFFLINE=1 ./test/cve-context.py <dir> # from the cache only, no requests

CI's scan is the cve-<arch> artifact (ARCH defaults to the host's), downloaded with gh
into output/cve-ci/<run>-<arch>/ once and reused after.

For each distinct (vulnerability, package, version) across every report in the
directory, from five public sources:

  EPSS     FIRST's Exploit Prediction Scoring System: the probability of exploitation in
           the next 30 days, and its percentile among all CVEs (api.first.org)
  KEV      CISA's Known Exploited Vulnerabilities catalogue: exploited in the wild
  Debian   the security tracker's verdict for sid: open, fixed (and in which version; a
           Debian revision of our upstream version means a patch exists), not affected
           (fixed_version 0), or urgency "unimportant"
  Ubuntu   the CVE tracker's priority (negligible, low, medium, high, critical)
  Red Hat  the threat severity and Product Security's statement, which is where "does
           not affect upstream" and "only our backport" are said

GO-/GHSA- advisories are looked up by the CVE grype relates them to; one without a CVE
gets EPSS and the trackers' "n/a". The Debian package is the CVE's entry for our
package's Debian source name when it has one (kernel is `linux`, Go's stdlib is
`golang-<major.minor>`), and otherwise the first Debian source that tracks the CVE.

Writes <dir>/cve-context.tsv (every column, one row per finding) and prints a markdown
table grouped by a hint, highest EPSS first within each:

  exploited (KEV)                  in CISA's catalogue: first, whatever else is said
  Debian patched this version      Debian fixed it in a revision of the upstream version
                                   we ship, so a patch exists to carry
  fixed in a newer release         Debian's fix is a later upstream version: a bump
  open in Debian too / not tracked nobody has a fix, or Debian has no opinion
  fixed before our version, Debian: not affected, distro: unimportant
                                   most likely a false positive (a CPE match with no
                                   version range, a downstream-only bug, a dispute)

The hint is where to look first, not a verdict: Debian's answer is about Debian's build of
the package, which can differ from ours in configure flags and patches.

Everything fetched is cached in ~/.cache/kaetzli/cve-context for a day. Like the other
CVE reports, this never fails: a source that cannot be reached is a note and an empty
column.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import sys
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import groupby
from pathlib import Path
from typing import TextIO

from kaetzli import repo
from kaetzli.cve.grype import cache_dir as kaetzli_cache
from kaetzli.gh import Gh
from kaetzli.http_cache import Cache
from kaetzli.report import Note, Report, run, tsv

REPO = "fwilhe2/kaetzli"
DEBIAN_URL = "https://security-tracker.debian.org/tracker/data/json"
KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
EPSS_URL = "https://api.first.org/data/v1/epss?cve="
REDHAT_URL = "https://access.redhat.com/hydra/rest/securitydata/cve/{}.json"
UBUNTU_URL = "https://ubuntu.com/security/cves/{}.json"

# --- the findings ----------------------------------------------------------------------


@dataclass
class Finding:
    id: str
    cve: str  # the id itself or its first related CVE; "" for an advisory without one
    pkg: str
    version: str
    severity: str | None = None
    cvss: Decimal | int | None = None  # the best score, as grype wrote it
    fix: str = ""
    fixed_in: str = ""
    docs: str = ""  # the reports it is in, comma-separated


def grype_reports(directory: Path) -> list[Path]:
    return [
        p
        for p in sorted((directory / "cve").glob("*.json"))
        if not p.name.endswith((".vex.json", ".sbom.json"))
    ]


def _finding(m: dict, doc: str) -> Finding:
    v = m["vulnerability"]
    related = m.get("relatedVulnerabilities") or []
    ids = [v["id"], *(r.get("id") for r in related)]
    scores = [c.get("metrics", {}).get("baseScore") for c in v.get("cvss") or []]
    for r in related:
        scores += [c.get("metrics", {}).get("baseScore") for c in r.get("cvss") or []]
    scores = [s for s in scores if s is not None]
    fix = v.get("fix") or {}
    return Finding(
        id=v["id"],
        cve=next((i for i in ids if i and i.startswith("CVE-")), ""),
        pkg=m["artifact"]["name"],
        version=m["artifact"]["version"],
        severity=v.get("severity"),
        cvss=max(scores) if scores else None,
        fix=fix.get("state") or "",
        fixed_in=",".join(fix.get("versions") or []),
        docs=doc,
    )


def distinct_findings(reports: Iterable[Path]) -> list[Finding]:
    """One per (id, package, version), as first listed, with every report it is in."""
    first: dict[tuple[str, str, str], Finding] = {}
    docs: dict[tuple[str, str, str], set[str]] = {}
    for path in reports:
        doc = json.loads(path.read_text(), parse_float=Decimal)
        for m in doc.get("matches") or []:
            f = _finding(m, path.stem)
            k = (f.id, f.pkg, f.version)
            first.setdefault(k, f)
            docs.setdefault(k, set()).add(path.stem)
    out = []
    for k in sorted(first):
        f = first[k]
        f.docs = ",".join(sorted(docs[k]))
        out.append(f)
    return out


# --- the sources -----------------------------------------------------------------------


@dataclass(frozen=True)
class Epss:
    epss: str  # as the API wrote it, which is what the TSV shows
    percentile: str | None


@dataclass
class Sources:
    debian: dict[str, list[dict]] = field(default_factory=dict)  # cve -> [{src, sid}]
    kev: dict[str, dict] = field(default_factory=dict)  # cve -> {added, ransomware}
    epss: dict[str, Epss] = field(default_factory=dict)
    redhat: dict[str, dict] = field(default_factory=dict)  # cve -> {severity, statement}
    ubuntu: dict[str, str] = field(default_factory=dict)  # cve -> priority


def batches(items: list[str], n: int) -> list[list[str]]:
    return [items[i : i + n] for i in range(0, len(items), n)]


def epss_batch_key(cves: list[str]) -> str:
    """A batch's cache file name: the bash version's, so one cache serves both."""
    return hashlib.sha256((" ".join(cves) + "\n").encode()).hexdigest()[:16]


def _json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _raw_number(v) -> str | None:
    return None if v is None else str(v)


def debian_index(tracker: dict, cves: set[str]) -> dict[str, list[dict]]:
    """The tracker (80 MB, source -> CVE -> verdicts) inverted to CVE -> [source, sid
    verdict], for our CVEs only, in the tracker's order of sources."""
    index: dict[str, list[dict]] = {}
    for src, entries in tracker.items():
        if not isinstance(entries, dict):
            continue
        for cve, entry in entries.items():
            if cve in cves:
                sid = ((entry or {}).get("releases") or {}).get("sid")
                index.setdefault(cve, []).append({"src": src, "sid": sid})
    return dict(sorted(index.items()))


def load_sources(cves: list[str], directory: Path, cache: Cache, note) -> Sources:
    """Every source, fetched unless the cache has it, read into one Sources."""
    for sub in ("redhat", "ubuntu", "epss"):
        (directory / sub).mkdir(parents=True, exist_ok=True)
    s = Sources()
    wanted = set(cves)

    if not cache.get(directory / "debian.json", DEBIAN_URL):
        note("Debian security tracker unreachable")
    if not cache.get(directory / "kev.json", KEV_URL):
        note("CISA KEV unreachable")

    # EPSS takes a comma-separated list; a hundred at a time keeps the URL short.
    for batch in batches(cves, 100):
        path = directory / "epss" / f"{epss_batch_key(batch)}.json"
        if cache.get(path, EPSS_URL + ",".join(batch)):
            for d in (_json(path) or {}).get("data") or []:
                s.epss[d["cve"]] = Epss(
                    _raw_number(d.get("epss")), _raw_number(d.get("percentile"))
                )
    if not s.epss:
        note("EPSS unreachable or knows none of these")

    # Red Hat and Ubuntu answer one CVE per request; eight at a time.
    def one(cve: str) -> None:
        cache.get(directory / "redhat" / f"{cve}.json", REDHAT_URL.format(cve))
        cache.get(directory / "ubuntu" / f"{cve}.json", UBUNTU_URL.format(cve))

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(one, cves))

    for cve in cves:
        rh = _json(directory / "redhat" / f"{cve}.json")
        if isinstance(rh, dict):
            statement = re.sub(r"\s+", " ", _alt(rh.get("statement"), ""))[:200]
            s.redhat[cve] = {
                "severity": _alt(rh.get("threat_severity"), ""),
                "statement": statement,
            }
        ub = _json(directory / "ubuntu" / f"{cve}.json")
        if isinstance(ub, dict):
            s.ubuntu[cve] = _alt(ub.get("priority"), "")

    tracker = _json(directory / "debian.json")
    if isinstance(tracker, dict):
        s.debian = debian_index(tracker, wanted)
    kev = _json(directory / "kev.json")
    if isinstance(kev, dict):
        for v in kev.get("vulnerabilities") or []:
            s.kev[v["cveID"]] = {
                "added": v.get("dateAdded"),
                "ransomware": v.get("knownRansomwareCampaignUse"),
            }
    return s


# --- the rules -------------------------------------------------------------------------


def _alt(value, default):
    """jq's `//`: the default for null and false only."""
    return default if value is None or value is False else value


def debian_source(pkg: str, version: str) -> str:
    """Our package name as Debian's source package, where they differ."""
    if pkg == "kernel":
        return "linux"
    if pkg == "podman":
        return "libpod"
    if pkg == "stdlib":
        return "golang-" + ".".join(version.split(".")[:2])
    if pkg == "golang.org/x/crypto":
        return "golang-go.crypto"
    if pkg.startswith("golang.org/x/"):
        return "golang-golang-x-" + pkg.split("/")[2]
    if pkg == "google.golang.org/grpc":
        return "golang-google-grpc"
    return pkg


def upstream_numbers(version: str) -> list[int]:
    """A Debian version as the upstream version it packages, as numbers to compare:
    "1:1.3.dfsg+really1.3.2-4" is 1.3.2, "1:10.2p1-6" is 10.2.1, "v0.59.0" is 0.59.0."""
    v = re.sub(r"^[0-9]+:", "", version, count=1)
    v = re.sub(r"^.*\+really", "", v, count=1)
    v = re.sub(r"-[^-]*$", "", v, count=1)
    v = re.sub(r"^v", "", v, count=1)
    v = re.sub(r"[+~].*$", "", v, count=1)
    return [int(n) for n in re.findall(r"[0-9]+", v)]


def against(debian_fixed: str, ours: str) -> str:
    """How a Debian fix relates to the version we ship: "same" (Debian patched this very
    upstream version, so a patch exists), "newer" (fixed by a later upstream release) or
    "older" (fixed before our version, so the match is most likely a false positive)."""
    d, o = upstream_numbers(debian_fixed), upstream_numbers(ours)
    if d == o:
        return "same"
    return "newer" if d > o else "older"


def _s(value) -> str:
    """A value as jq's string interpolation writes it."""
    return "null" if value is None else str(value)


def debian_verdict(entry: dict | None) -> str:
    if entry is None:
        return ""
    src, sid = entry["src"], entry.get("sid")
    if sid is None:
        verdict = f"{src}: not in sid"
    elif sid.get("status") == "resolved" and sid.get("fixed_version") == "0":
        verdict = f"{src}: not affected"
    elif sid.get("status") == "resolved":
        verdict = f"{src}: fixed in {_s(sid.get('fixed_version'))}"
    else:
        verdict = f"{src}: {_s(sid.get('status'))}"
    if "unimportant" in str(_alt((sid or {}).get("urgency"), "")):
        verdict += " (unimportant)"
    return verdict


def debian_entry(entries: list[dict], src: str) -> dict | None:
    """Our package's own entry, else the first that sid tracks, else the first."""
    for wanted in (
        lambda e: e["src"] == src,
        lambda e: e.get("sid") is not None,
        lambda e: True,
    ):
        for e in entries:
            if wanted(e):
                return e
    return None


@dataclass
class Row:
    finding: Finding
    epss: Epss | None
    kev: dict | None
    debian: str
    ubuntu: str
    redhat: str
    redhat_statement: str
    hint: str = ""

    @property
    def epss_value(self) -> float:
        return float(self.epss.epss) if self.epss and self.epss.epss is not None else 0.0

    @property
    def percentile_value(self) -> float:
        p = self.epss.percentile if self.epss else None
        return float(p) if p is not None else 0.0


def row(f: Finding, s: Sources) -> Row:
    src = debian_source(f.pkg, f.version)
    entry = debian_entry(s.debian.get(f.cve, []), src)
    sid = _alt((entry or {}).get("sid"), {})
    # Versions compare only within one package: the fallback source (the Go stdlib for
    # an x/ module) has a version line of its own.
    relation = ""
    if sid.get("status") == "resolved" and _alt(sid.get("fixed_version"), "0") != "0":
        relation = against(sid["fixed_version"], f.version) if entry["src"] == src else "elsewhere"
    rh = s.redhat.get(f.cve, {})
    r = Row(
        finding=f,
        epss=s.epss.get(f.cve),
        kev=s.kev.get(f.cve),
        debian=debian_verdict(entry),
        ubuntu=s.ubuntu.get(f.cve, ""),
        redhat=rh.get("severity", ""),
        redhat_statement=rh.get("statement", ""),
    )
    if r.kev:
        r.hint = "1 exploited (KEV)"
    elif relation == "same":
        r.hint = "2 Debian patched this version"
    elif relation == "newer":
        r.hint = "3 fixed in a newer release"
    elif relation == "older":
        r.hint = "5 fixed before our version (likely FP)"
    elif "not affected" in r.debian:
        r.hint = "5 Debian: not affected"
    elif "unimportant" in r.debian or r.ubuntu == "negligible":
        r.hint = "5 distro: unimportant"
    elif relation == "elsewhere":
        r.hint = "4 Debian fixed the copy in another package"
    elif entry is None:
        r.hint = "4 not tracked by Debian"
    else:
        r.hint = "4 open in Debian too"
    if r.percentile_value >= 0.9 and not r.hint.startswith("5"):
        r.hint += ", EPSS top 10%"
    return r


def rows(findings: list[Finding], s: Sources) -> list[Row]:
    """By hint, then highest EPSS first; ties keep the findings' order."""
    return sorted((row(f, s) for f in findings), key=lambda r: (r.hint[:1], -r.epss_value))


# --- the output ------------------------------------------------------------------------

TSV_COLUMNS = [
    "hint", "id", "cve", "package", "version", "severity", "cvss", "epss", "percentile",
    "kev", "debian", "ubuntu", "redhat", "redhat_statement", "fix", "fixed_in", "reports",
]  # fmt: skip


def tsv_lines(rs: list[Row]) -> list[str]:
    lines = [tsv(TSV_COLUMNS)]
    for r in rs:
        f = r.finding
        lines.append(
            tsv(
                [
                    r.hint[2:],
                    f.id,
                    f.cve,
                    f.pkg,
                    f.version,
                    f.severity,
                    f.cvss,
                    r.epss.epss if r.epss else None,
                    r.epss.percentile if r.epss else None,
                    r.kev["added"] if r.kev else None,
                    r.debian,
                    r.ubuntu,
                    r.redhat,
                    r.redhat_statement,
                    f.fix,
                    f.fixed_in,
                    f.docs,
                ]
            )
        )
    return lines


def percent(value: str | None) -> str:
    """A probability as a percentage with one decimal, rounded half up (jq's round)."""
    if value is None:
        return ""
    tenths = math.floor(float(value) * 1000 + 0.5)
    whole, frac = divmod(tenths, 10)
    return f"{whole}%" if frac == 0 else f"{whole}.{frac}%"


def markdown_lines(rs: list[Row]) -> list[str]:
    lines = [
        "| hint | id | package | sev | EPSS (pctl) | Debian sid | Ubuntu | Red Hat |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rs:
        f = r.finding
        ident = f.id + (f" ({f.cve})" if f.cve and f.cve != f.id else "")
        epss = "" if r.epss is None else f"{percent(r.epss.epss)} ({percent(r.epss.percentile)})"
        lines.append(
            f"| {r.hint[2:]} | {ident} | {f.pkg} {f.version} | {_s(f.severity)} | {epss} "
            f"| {r.debian} | {r.ubuntu} | {r.redhat} |"
        )
    labels = sorted(r.hint[2:] for r in rs)
    counts = [f"{label}: {len(list(g))}" for label, g in groupby(labels)]
    return [*lines, "", " · ".join(counts)]


def report(
    directory: Path,
    cache_dir: Path,
    cache: Cache,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> list[Row]:
    stdout, stderr = stdout or sys.stdout, stderr or sys.stderr

    def note(msg: str) -> None:
        print(f"_{msg}_", file=stderr)

    reports = grype_reports(directory)
    if not reports:
        note(
            f"no grype reports in {directory}/cve/ (run test/cve-scan.py, or give no "
            "directory to use CI's)"
        )
        return []
    findings = distinct_findings(reports)
    cves = sorted({f.cve for f in findings if f.cve})
    note(f"{len(findings)} findings, {len(cves)} distinct CVEs, from {len(reports)} reports")
    rs = rows(findings, load_sources(cves, cache_dir, cache, note))
    out = directory / "cve-context.tsv"
    out.write_text("\n".join(tsv_lines(rs)) + "\n")
    for line in markdown_lines(rs):
        print(line, file=stdout)
    note(f"every column, Red Hat's statements included: {out}")
    return rs


# --- which scan ------------------------------------------------------------------------


def which_scan(directory: str | None, run: str | None, arch: str, gh) -> Path:
    """The directory given; else this checkout's own scan in output/; else CI's newest
    (or RUN's), downloaded once per run into output/cve-ci/<run>-<arch>/."""
    if directory:
        return Path(directory)
    if grype_reports(Path("output")) and not run:
        return Path("output")
    stderr = Report(stdout=sys.stderr)
    if problem := gh.problem():
        raise Note(f"no scan in output/ and {problem} to fetch CI's", stderr)
    run = run or gh.newest_run_with(f"cve-{arch}", workflow="ci.yml", branch="main")
    if not run:
        raise Note(
            f"no successful run on main with a cve-{arch} artifact among the last 30", stderr
        )
    if not run.isdigit():
        print(f"error: RUN '{run}' is not a run id", file=sys.stderr)
        sys.exit(2)
    d = Path("output/cve-ci") / f"{run}-{arch}"
    if not grype_reports(d):
        print(f"_fetching cve-{arch} from run {run}_", file=sys.stderr)
        tmp = d.with_name(d.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        if not gh.download(run, f"cve-{arch}", tmp):
            shutil.rmtree(tmp, ignore_errors=True)
            raise Note(f"could not download cve-{arch} from run {run}", stderr)
        shutil.rmtree(d, ignore_errors=True)
        tmp.rename(d)
    print(f"_run {run} ({arch}): https://github.com/{REPO}/actions/runs/{run}_", file=sys.stderr)
    return d


def main(argv: list[str]) -> int:
    repo.enter_root()
    try:
        arch = repo.normalize_arch(os.environ.get("ARCH"))
    except repo.UnsupportedArch as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    directory = which_scan(argv[0] if argv else None, os.environ.get("RUN"), arch, Gh(repo=REPO))
    cache = Cache(offline=bool(os.environ.get("OFFLINE")))
    report(directory, kaetzli_cache() / "cve-context", cache)
    return 0


if __name__ == "__main__":
    sys.exit(run(main, sys.argv[1:]))
