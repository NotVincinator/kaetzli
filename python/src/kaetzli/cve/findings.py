"""grype's JSON reports, read once and asked the questions every CVE report asks.

A finding is one (vulnerability, package, version): grype lists one per location, and a
CVE in one package is counted once however many files it is found in. Where the same
finding is listed more than once, the first listing is the one that counts.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from itertools import groupby
from pathlib import Path

from kaetzli.cve.summary import Counts


@dataclass
class Report:
    matches: list[dict]
    ignored: list[dict]


def load(path: Path) -> Report:
    # Decimal keeps a CVSS score as grype wrote it ("5.0", not 5).
    doc = json.loads(Path(path).read_text(), parse_float=Decimal)
    return Report(doc.get("matches") or [], doc.get("ignoredMatches") or [])


def merge(reports: Iterable[Report]) -> Report:
    matches: list[dict] = []
    ignored: list[dict] = []
    for r in reports:
        matches += r.matches
        ignored += r.ignored
    return Report(matches, ignored)


def key(match: dict) -> tuple[str, str, str]:
    return (match["vulnerability"]["id"], match["artifact"]["name"], match["artifact"]["version"])


def severity(match: dict) -> str:
    return match["vulnerability"].get("severity") or "Unknown"


def first_of_each(matches: Iterable[dict]) -> list[dict]:
    """One match per finding, the first listed, ordered by finding."""
    seen: dict[tuple[str, str, str], dict] = {}
    for m in matches:
        seen.setdefault(key(m), m)
    return [seen[k] for k in sorted(seen)]


def vex_patched(report: Report) -> list[dict]:
    """The matches a VEX statement closed: grype moved them to ignoredMatches."""
    return [
        m
        for m in report.ignored
        if any(r.get("namespace") == "vex" for r in m.get("appliedIgnoreRules") or [])
    ]


def counts(report: Report) -> Counts:
    open_ = first_of_each(report.matches)
    sev = [severity(m).lower() for m in open_]
    return Counts(
        total=len(open_),
        critical=sev.count("critical"),
        high=sev.count("high"),
        medium=sev.count("medium"),
        low=sev.count("low"),
        other=sum(s not in ("critical", "high", "medium", "low") for s in sev),
        fixable=sum((m["vulnerability"].get("fix") or {}).get("state") == "fixed" for m in open_),
        patched=len({key(m) for m in vex_patched(report)}),
    )


def most_affected(report: Report, n: int = 12) -> list[tuple[str, str, int]]:
    """(package, version, distinct CVEs), most first; ties by package name."""
    findings = sorted({key(m) for m in report.matches})
    by_pkg = groupby(sorted(findings, key=lambda f: f[1]), key=lambda f: f[1])
    rows = []
    for pkg, group in by_pkg:
        group = list(group)
        rows.append((pkg, group[0][2], len(group)))
    rows.sort(key=lambda r: -r[2])
    return rows[:n]


def patched(report: Report) -> list[tuple[str, str, str, str]]:
    """(id, severity, package, version) of each finding VEX closed, by package then id."""
    rows = {
        (m["vulnerability"]["id"], severity(m), m["artifact"]["name"], m["artifact"]["version"])
        for m in vex_patched(report)
    }
    # Ordered as jq orders the objects ({id, sev, pkg, ver} sorts by key name: id, pkg,
    # sev, ver), then by package and id, stably.
    ordered = sorted(rows, key=lambda r: (r[0], r[2], r[1], r[3]))
    return sorted(ordered, key=lambda r: (r[2], r[0]))
