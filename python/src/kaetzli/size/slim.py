"""Our container image against the one everybody else starts from:

    ./test/vs-debian-slim.py                    # output/rootfs-size-oci.txt vs debian-slim
    DEBIAN_SLIM=debian:forky-slim ./test/vs-debian-slim.py

test/size-budget.txt caps the image against a number somebody here wrote down, which
answers "did it grow?" and nothing else. This asks the other question: is a
built-from-source image still smaller than the distribution base image it would otherwise
be replacing? That is the claim this project makes every time it says "minimal", and the
one no ceiling in this repository can check, because what it compares against lives on a
registry and moves on its own.

Exceeding debian-slim is a failure. Not because a megabyte matters on its own, but
because at that point the honest advice would be to use debian-slim: it ships a package
manager, security updates and a decade of packaging, and this ships none of that.

Both sides are measured the same way, apparent bytes of the assembled tree by the du and
find invocations image/build-rootfs.sh uses, so the two reports can be subtracted. Ours is
read back from the report that build wrote (the assembled tree only exists inside that
container); the baseline is exported from the image and walked here.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from kaetzli import repo
from kaetzli.report import Report, run
from kaetzli.size.sizes import SizeReport, mib, read

# Pinned to a release rather than :stable-slim on purpose. A floating tag would move the
# comparison under a build that changed nothing, and "CI went red because Debian cut a
# release" is not a signal about this image.
BASELINE = "debian:trixie-slim"
THEIRS = "output/rootfs-size-debian-slim.txt"


def _lines(argv: list[str]) -> list[tuple[int, str]]:
    out = subprocess.run(argv, check=True, capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        n, _, path = line.replace("\t", " ", 1).partition(" ")
        rows.append((int(n), path))
    # sort -rn, ties by the whole line, as build-rootfs.sh's pipelines do
    return sorted(rows, key=lambda r: (r[0], f"{r[0]} {r[1]}"), reverse=True)


def tree_report(root: Path, baseline: str, arch: str) -> str:
    """The report build-rootfs.sh writes, of a tree here. Deliberately the same
    measurements rather than shared code: that script runs inside the assembly container,
    and a comparison whose two sides were counted differently would be worse than none."""
    root = Path(root)
    prefix = f"{root}/"
    total = subprocess.run(
        ["du", "-sb", str(root)], check=True, capture_output=True, text=True
    ).stdout.split("\t", 1)[0]
    lines = [
        f"# {baseline} ({arch}) filesystem, sizes in bytes. Written by test/vs-debian-slim.py.",
        f"total {total}",
    ]
    for n, path in _lines(["du", "-b", "--max-depth=2", str(root)]):
        if path == str(root) or n < 65536:
            continue
        lines.append(f"dir {n} {path.removeprefix(prefix)}")
    files = _lines(["find", str(root), "-type", "f", "-printf", "%s %p\\n"])
    lines += [f"file {n} {path.removeprefix(prefix)}" for n, path in files[:25]]
    return "\n".join(lines) + "\n"


def measure(baseline: str, arch: str, dest: Path) -> None:
    """The baseline's report into dest. `podman export` flattens the image to a tar of its
    filesystem, the closest thing to the tree build-rootfs.sh measures: no layer
    metadata, no whiteouts. Nothing is run from the image, so a foreign architecture
    works on any runner."""
    print(f"measuring {baseline} ({arch})...", flush=True)
    subprocess.run(
        ["podman", "pull", "--quiet", "--arch", arch, baseline],
        check=True, stdout=subprocess.DEVNULL,
    )  # fmt: skip
    cid = subprocess.run(
        ["podman", "create", "--quiet", "--arch", arch, baseline],
        check=True, capture_output=True, text=True,
    ).stdout.strip()  # fmt: skip
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            # --no-same-owner: every number here is a size, none an ownership, and
            # Debian's base image has no device nodes, so unprivileged is complete.
            export = subprocess.Popen(["podman", "export", cid], stdout=subprocess.PIPE)
            untar = subprocess.run(
                ["tar", "-x", "-C", str(root), "--no-same-owner"], stdin=export.stdout
            )
            export.stdout.close()
            if export.wait() != 0 or untar.returncode != 0:
                raise subprocess.CalledProcessError(1, ["podman", "export", cid])
            Path(dest).write_text(tree_report(root, baseline, arch))
    finally:
        subprocess.run(["podman", "rm", "-f", cid], capture_output=True, check=False)


def compare(ours: SizeReport, theirs: SizeReport, baseline: str, arch: str) -> int:
    percent = ours.total * 100 // theirs.total
    delta = ours.total - theirs.total

    # The directories both images have, largest first by whichever side is bigger: the
    # "why" half, which reads best merged. usr/lib against usr/lib says something; two
    # lists side by side say much less.
    a_dirs, b_dirs = ours.dir_sizes(), theirs.dir_sizes()
    rows = []
    for path in {*a_dirs, *b_dirs}:
        a, b = a_dirs.get(path, 0), b_dirs.get(path, 0)
        rows.append((max(a, b), a, b, path))
    rows.sort(key=lambda r: (r[0], f"{r[0]} {r[1]} {r[2]} {r[3]}"), reverse=True)

    print()
    print(f"container image size ({arch}):")
    print(f"  {mib(ours.total):>10} MiB  kaetzli")
    print(f"  {mib(theirs.total):>10} MiB  {baseline}")
    if delta < 0:
        print(f"  → {percent}% of debian-slim, {mib(-delta)} MiB smaller")
    else:
        print(f"  → {percent}% of debian-slim, {mib(delta)} MiB LARGER")
    print()
    print("  where the bytes are:")
    print(f"    {'kaetzli':>8}  {'debian':>8}  directory")
    for _, a, b, path in rows:
        print(f"    {mib(a):>8}  {mib(b):>8}  {path}")
    print()
    print("  largest files, kaetzli:")
    for n, path in ours.files[:10]:
        print(f"    {mib(n):>8}  {path}")
    print()
    print(f"  largest files, {baseline}:")
    for n, path in theirs.files[:10]:
        print(f"    {mib(n):>8}  {path}")

    which = "smaller" if delta < 0 else "LARGER"
    Report.summary_only().lines(
        [
            f"## Container image vs debian-slim — {arch}",
            "",
            f"**{mib(ours.total)} MiB** against **{mib(theirs.total)} MiB** for `{baseline}` "
            f"— {percent}%, {mib(abs(delta))} MiB {which}.",
            "",
            "| directory | kaetzli MiB | debian-slim MiB |",
            "| --- | ---: | ---: |",
            *(f"| `{path}` | {mib(a)} | {mib(b)} |" for _, a, b, path in rows),
            "",
            "<details><summary>Largest files</summary>",
            "",
            "| kaetzli | MiB |",
            "| --- | ---: |",
            *(f"| `{path}` | {mib(n)} |" for n, path in ours.files[:10]),
            "",
            f"| {baseline} | MiB |",
            "| --- | ---: |",
            *(f"| `{path}` | {mib(n)} |" for n, path in theirs.files[:10]),
            "",
            "</details>",
        ]
    )

    if delta > 0:
        print()
        sys.stdout.flush()
        print(
            f"error: the container image is {mib(delta)} MiB bigger than {baseline} on "
            f"{arch}.\n"
            "       The breakdown above says which directory; take it back out. There is no\n"
            "       number to raise here on purpose — the point of building this from source\n"
            "       is that the result is smaller than the base image it replaces, and past\n"
            "       that line the honest answer is to use debian-slim, which also ships a\n"
            "       package manager and security updates.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str]) -> int:
    repo.enter_root()
    given = argv[0] if argv else "output/rootfs-size-oci.txt"
    baseline = os.environ.get("DEBIAN_SLIM") or BASELINE
    arch = repo.normalize_arch(os.environ.get("ARCH"))
    if not Path(given).is_file():
        print(f"error: no size report at {given}", file=sys.stderr)
        print(
            "       image/build-rootfs.sh writes one per flavour into output/; "
            "build the OCI image first",
            file=sys.stderr,
        )
        return 1
    measure(baseline, arch, Path(THEIRS))
    ours, theirs = read(Path(given)), read(Path(THEIRS))
    if ours.total <= 0 or theirs.total <= 0:
        print("error: one of the reports has no total", file=sys.stderr)
        return 1
    return compare(ours, theirs, baseline, arch)


if __name__ == "__main__":
    sys.exit(run(main, sys.argv[1:]))
