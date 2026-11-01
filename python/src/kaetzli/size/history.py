"""How the image size has moved, for both flavours, as a job summary:

    ./test/size-history.py              # this architecture
    ./test/size-history.py arm64        # name one
    RUNS=20 ./test/size-history.py      # look further back

test/rootfs-size.py answers "is this image allowed to be this big", a question about one
build against a number somebody wrote down. This answers a different one: *which way is
it going*, and did this change move it. A ceiling only ever fires once, after the growth
has happened and usually some commits after the one that caused it; a trend shows the
commit that did it, on the run that did it.

The history is the rootfs-size-<arch> artifact the `rootfs` job uploads on every run, so
nothing new is stored and there is no state in the repository. It reaches only as far
back as artifact retention.

This never fails a build. It reports; test/rootfs-size.py enforces. A missing gh, an
expired artifact or a first run on a new branch end in a note, not a non-zero exit.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from kaetzli import repo
from kaetzli.gh import Gh
from kaetzli.report import Note, Report, run, sparkline
from kaetzli.size.sizes import SizeReport, delta, mib, read_or_empty

OUTPUT = "output"
FLAVOURS = ("erofs", "oci")
# Half of the 0.1 MiB the tables print to: a directory that moved by less is a different
# build of the same content, not news, and ±0.0 rows bury the one row that matters.
NEWS = 51200


@dataclass
class Build:
    id: str
    sha: str
    created: str  # YYYY-MM-DDTHH:MM
    reports: dict[str, SizeReport]  # the flavours whose report the artifact has

    def total(self, flavour: str) -> int:
        r = self.reports.get(flavour)
        return r.total if r else 0


def rename_ext4(d: Path) -> None:
    """Builds from before the disk image was EROFS called it ext4. The report measures
    the same assembled tree either way, so it continues the series."""
    ext4, erofs = d / "rootfs-size-ext4.txt", d / "rootfs-size-erofs.txt"
    if ext4.is_file() and not erofs.exists():
        ext4.rename(erofs)


def collect(
    gh: Gh, arch: str, runs: int, workdir: Path, workflow: str, branch: str, skip_run: str
) -> list[Build]:
    """The last `runs` green builds on the branch that still have the artifact, oldest
    first. `success` matters: a run that failed before `rootfs` has nothing to fetch.
    Newest first out of the API, stopping once there are enough: artifacts expire
    oldest-first, so the tail is where the misses are."""
    builds = []
    for r in gh.successful_runs(workflow, branch, limit=runs * 2):
        if len(builds) >= runs:
            break
        if r.id == skip_run:
            continue
        d = workdir / r.id
        if not gh.download(r.id, f"rootfs-size-{arch}", d):
            continue
        rename_ext4(d)
        reports = {
            f: read_or_empty(d / f"rootfs-size-{f}.txt")
            for f in FLAVOURS
            if (d / f"rootfs-size-{f}.txt").is_file()
        }
        builds.append(Build(r.id, r.sha, r.created[:16], reports))
    builds.reverse()  # the direction a graph reads
    return builds


def moved(now: SizeReport, base: SizeReport) -> list[tuple[str, int, int]]:
    """(path, now, Δ) for every directory that moved by NEWS or more, by how far rather
    than which way: the question is "what did it", and that is the top row either way."""
    b, seen, rows = base.dir_sizes(), set(), []
    for n, path in now.dirs:
        seen.add(path)
        d = n - b.get(path, 0)
        if abs(d) >= NEWS:
            rows.append((abs(d), path, n, d))
    rows += [(n, path, 0, -n) for path, n in b.items() if path not in seen and n >= NEWS]
    rows.sort(key=lambda r: (-r[0], f"{r[0]} {r[1]} {r[2]} {r[3]}"))
    return [(path, n, d) for _, path, n, d in rows]


def render(builds: list[Build], current: dict[str, SizeReport], arch: str, branch: str,
           here: str) -> list[str]:  # fmt: skip
    # The headline: one row per flavour, the shape on the left and the numbers on the
    # right. `main` is the newest build on the branch: on a pull request what the change
    # is judged against, on a push to main the commit before.
    lines = [
        f"| flavour | last {len(builds)} builds on `{branch}` → now | {branch} | this build | Δ |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for f in FLAVOURS:
        now = current[f].total
        series = [b.total(f) for b in builds if b.total(f)]
        baseline = series[-1] if series else 0
        lines.append(
            f"| `{f}` | `{sparkline([*series, now])}` | {mib(baseline)} | **{mib(now)}** "
            f"| {delta(now - baseline)} |"
        )
    lines += [
        "",
        "MiB, apparent size of the assembled tree — the same number `test/rootfs-size.py` "
        "holds to `test/size-budget.txt`.",
        "",
    ]

    # Where it moved, per directory, against the newest build: what turns "it grew" into
    # which directory did it on which commit.
    newest = builds[-1]
    for f in FLAVOURS:
        if f not in newest.reports:
            continue
        rows = moved(current[f], newest.reports[f])
        if not rows:
            continue
        lines += [
            f"<details><summary>Where <code>{f}</code> changed against `{branch}`</summary>",
            "",
            "| directory | now | Δ |",
            "| --- | ---: | ---: |",
            *(f"| `{path}` | {mib(n)} | {delta(d)} |" for path, n, d in rows),
            "",
            "</details>",
            "",
        ]

    # The numbers behind the sparklines, for when the shape raises a question it cannot
    # answer.
    lines += [
        "<details><summary>Run by run</summary>",
        "",
        "| date | commit | erofs | oci |",
        "| --- | --- | ---: | ---: |",
        *(
            f"| {b.created.replace('T', ' ', 1)} | `{b.sha[:7]}` "
            f"| {mib(b.total('erofs'))} | {mib(b.total('oci'))} |"
            for b in builds
        ),
        f"| **this build** | `{here[:7]}` | **{mib(current['erofs'].total)}** "
        f"| **{mib(current['oci'].total)}** |",
        "",
        "</details>",
    ]
    return lines


def history(
    gh: Gh,
    arch: str,
    runs: int,
    out_dir: Path,
    rep: Report,
    here: str,
    workflow: str = "ci.yml",
    branch: str = "main",
    skip_run: str = "",
) -> None:
    current = {f: read_or_empty(Path(out_dir) / f"rootfs-size-{f}.txt") for f in FLAVOURS}
    with tempfile.TemporaryDirectory() as workdir:
        problem = gh.problem()
        builds = (
            [] if problem else collect(gh, arch, runs, Path(workdir), workflow, branch, skip_run)
        )
        rep.lines([f"## Image size over time — {arch}", ""])
        if not builds:
            rep.lines(["This build:", "", "| flavour | size |", "| --- | ---: |"])
            rep.lines(f"| `{f}` | {mib(current[f].total)} MiB |" for f in FLAVOURS)
            rep.out()
            if problem:
                raise Note(f"{problem}, so there is no history to compare against.", rep)
            raise Note(
                f"no size artifacts found on `{branch}` — they expire, and a branch that has "
                "never run one has none.",
                rep,
            )
        rep.lines(render(builds, current, arch, branch, here))


def head() -> str:
    if sha := os.environ.get("GITHUB_SHA"):
        return sha
    p = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo.ROOT, capture_output=True, text=True, check=False
    )
    return p.stdout.strip() if p.returncode == 0 else "local"


def main(argv: list[str]) -> int:
    repo.enter_root()
    try:
        arch = repo.normalize_arch((argv[0] if argv else None) or os.environ.get("ARCH"))
    except repo.UnsupportedArch:
        print("usage: size-history.py [amd64|arm64]", file=sys.stderr)
        return 2
    # Without this build there is nothing to compare against and no reason to go to the
    # network, so it is checked first.
    if not all((Path(OUTPUT) / f"rootfs-size-{f}.txt").is_file() for f in FLAVOURS):
        print(
            f"no size reports in {OUTPUT}/ — build an image first "
            "(image/build-rootfs.sh writes them)",
            file=sys.stderr,
        )
        return 0
    history(
        Gh(), arch, int(os.environ.get("RUNS", "12")), Path(OUTPUT), Report.from_env(),
        here=head(),
        workflow=os.environ.get("WORKFLOW", "ci.yml"),
        branch=os.environ.get("BASE_BRANCH", "main"),
        skip_run=os.environ.get("GITHUB_RUN_ID", ""),
    )  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(run(main, sys.argv[1:]))
