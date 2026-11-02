"""Print the latest version a package's upstream has released:

    tools/upstream.py coreutils
    9.8

Where to look is declared in the package's env.sh. Nothing is needed for the common
case — a mirror directory holding every release side by side — because that is the
directory $URL already points into. The knobs, all optional:

  UPSTREAM_GITHUB   owner/repo. Take versions from the repo's GitHub releases and tags.
                    For projects whose downloads live on GitHub, where there is no
                    listing to scrape.
  UPSTREAM_INDEX    URL of an HTML directory listing to scrape. Defaults to the
                    directory $URL lives in.
  UPSTREAM_SUBDIR   ERE matching per-release subdirectories of UPSTREAM_INDEX. When
                    set, the newest matching subdirectory is scraped instead of the
                    index itself — kernel.org files util-linux tarballs one level
                    down, in v2.41/.
  UPSTREAM_REGEX    ERE matching release file names, with the version in group 1.
                    Defaults to $TARBALL with the version replaced by a number
                    pattern, e.g. coreutils-([0-9]+(\\.[0-9]+)*)\\.tar\\.gz.
  UPSTREAM_SED      sed -E expression applied to every candidate before it is judged,
                    for upstreams whose releases aren't named after the version —
                    expat tags 2.8.2 as R_2_8_2. It is run by sed, not translated.
  UPSTREAM_IGNORE   ERE of versions to skip.
  UPSTREAM_NUM      ERE of what a release version looks like, replacing NUM below for
                    one package. tz numbers its releases 2026e.

With --vendor, the same for the second tarball of a package that gives it a version of
its own (VENDOR_VERSION), read from VENDOR_UPSTREAM_* instead.

Only plain numeric versions are ever considered, so alphas, betas and release
candidates never show up as an update. The patterns are the env.sh's EREs, matched by
Python's re, which reads every one of them the same way.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass

from kaetzli import repo
from kaetzli.updates import versort
from kaetzli.updates.http import FetchError, Http

# What a version looks like. Dotted numbers, plus the one suffix an upstream here
# actually uses: portable OpenSSH numbers itself <upstream>p<portable>, so 10.5p1 is a
# release and 10.5 is not a thing that was ever published. Without the suffix openssh
# fails twice over — the default regex would not match its tarball, and the "plain
# numeric versions only" filter would drop the candidate even if it had.
#
# It stays this narrow deliberately. The filter exists to keep alphas, betas and release
# candidates from being proposed as updates, and `p<digits>` is the only decoration in
# this set that is a final release rather than a pre-release.
NUM = r"[0-9]+(\.[0-9]+)*(p[0-9]+)?"

KNOBS = ("GITHUB", "INDEX", "SUBDIR", "REGEX", "SED", "IGNORE", "NUM")


class UpstreamError(Exception):
    pass


@dataclass
class Source:
    pkg: str
    version: str
    tarball: str
    url: str
    github: str = ""
    index: str = ""
    subdir: str = ""
    regex: str = ""
    sed: str = ""
    ignore: str = ""
    num: str = ""

    @classmethod
    def of(cls, pkg: str, vendor: bool = False) -> Source:
        """Read through bash from env.sh, the vendor tarball's with vendor=True."""
        p = "VENDOR_" if vendor else ""
        names = [f"{p}VERSION", f"{p}TARBALL", f"{p}URL"] + [f"{p}UPSTREAM_{k}" for k in KNOBS]
        *values, local = repo.env_get(pkg, *names, "LOCAL_SOURCE")
        if local:
            raise UpstreamError(f"{pkg}: local source, no upstream")
        if vendor and not values[0]:
            raise UpstreamError(f"{pkg}: no VENDOR_VERSION; its vendor tarball follows VERSION")
        return cls(pkg, *values)


def default_regex(tarball: str, version: str, num: str) -> str:
    """The tarball's name with its version replaced by a number pattern."""
    before, _, after = tarball.partition(version)
    if not _:
        return re.escape(tarball)
    return f"{re.escape(before)}({num}){re.escape(after)}"


def _grep_o(pattern: str, text: str) -> list[str]:
    """grep -oE: every match, line by line."""
    rx = re.compile(pattern)
    return [m[0] for line in text.splitlines() for m in rx.finditer(line) if m[0]]


def index_versions(http: Http, url: str, regex: str) -> list[str]:
    """Each match's group 1 on a listing. An unreachable listing is an error; one that
    holds nothing matching is an empty answer."""
    out = []
    for whole in _grep_o(regex, http.get(url)):
        m = re.fullmatch(regex, whole)
        out.append(m[1] if m and m[1] is not None else whole)
    return out


def github_versions(http: Http, repository: str) -> list[str]:
    """Tags and releases both, because neither is complete on its own: kmod tags every
    release but only writes release notes for some, and a repo with thousands of tags
    could push the newest ones off the first page of the tags API."""
    api = f"https://api.github.com/repos/{repository}"
    tags = [t["name"] for t in json.loads(http.github(f"{api}/tags?per_page=100"))]
    releases = [
        r["tag_name"]
        for r in json.loads(http.github(f"{api}/releases?per_page=100"))
        if not (r.get("draft") or r.get("prerelease"))
    ]
    return [v.removeprefix("v") for v in tags + releases]


def sed(expression: str, values: list[str]) -> list[str]:
    """UPSTREAM_SED stays a sed expression, so sed runs it."""
    r = subprocess.run(
        ["sed", "-E", expression],
        input="".join(f"{v}\n" for v in values),
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise UpstreamError(f"sed -E '{expression}': {r.stderr.strip()}")
    return r.stdout.splitlines()


def candidates(src: Source, http: Http, num: str) -> list[str]:
    regex = src.regex or default_regex(src.tarball, src.version, num)
    if src.github:
        return github_versions(http, src.github)
    index = src.index or src.url.rsplit("/", 1)[0] + "/"
    if not src.subdir:
        return index_versions(http, index, regex)
    dirs = list(reversed(versort.sort(_grep_o(src.subdir, http.get(index)), unique=True)))
    if not dirs:
        raise UpstreamError(f"{src.pkg}: no subdirectory matching '{src.subdir}' at {index}")
    # Newest first, stopping at the first directory that actually holds a release: the
    # directory for a new series appears before its first final release, so the newest
    # one can contain nothing but release candidates for a while.
    for d in dirs:
        if found := index_versions(http, f"{index.rstrip('/')}/{d}", regex):
            return found
    return []


def latest(src: Source, http: Http) -> str:
    num = src.num or NUM
    try:
        found = candidates(src, http, num)
    except FetchError as e:
        raise UpstreamError(f"{src.pkg}: {e}") from e
    if src.sed:
        found = sed(src.sed, found)
    # Only plain numeric versions, so 6.6-rc1 and 20250101 snapshots stay out.
    found = [v for v in found if re.search(f"^{num}$", v)]
    if src.ignore:
        found = [v for v in found if not re.search(f"^{src.ignore}$", v)]
    if not found:
        raise UpstreamError(f"{src.pkg}: found no versions upstream")
    return versort.sort(found, unique=True)[-1]


def package_name(arg: str) -> str:
    """`coreutils`, `packages/coreutils` or `packages/coreutils/`, as tools/lib.sh's."""
    p = arg.rstrip("/").removeprefix("packages/")
    if not p or not (repo.ROOT / "packages" / p / "env.sh").is_file():
        raise UpstreamError(f"unknown package '{p}' (no packages/{p}/env.sh)")
    return p


def main(argv: list[str], http: Http | None = None) -> int:
    vendor = bool(argv) and argv[0] == "--vendor"
    args = argv[1:] if vendor else argv
    if len(args) != 1:
        print("usage: tools/upstream.py [--vendor] <package>", file=sys.stderr)
        return 1
    repo.enter_root()
    try:
        src = Source.of(package_name(args[0]), vendor)
        print(latest(src, http or Http()))
    except UpstreamError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
