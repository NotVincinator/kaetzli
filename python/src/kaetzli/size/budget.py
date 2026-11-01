"""What an assembled image weighs, and whether that is still allowed:

    ./test/rootfs-size.py                       # the EROFS disk
    ./test/rootfs-size.py oci                   # the container image
    ARCH=arm64 ./test/rootfs-size.py erofs some/report.txt   # a report from elsewhere

image/build-rootfs.sh writes the report: it is the only place the assembled tree exists,
since rootfs/ is the input and still carries everything the trim removed. This reads it
back, prints where the bytes are, and fails when the total is over the ceiling in
test/size-budget.txt.

The ceiling is the point. An image grows the way a garden grows over: never in one
visible step, always a package that started installing a new data directory or a trim
rule that quietly stopped matching. Nothing else in CI would ever fail over that, so the
only way to notice is to have written down what the size was allowed to be, and to have
to change that number on purpose.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from kaetzli import repo
from kaetzli.report import Report, run
from kaetzli.size.sizes import mib, read

BUDGET = "test/size-budget.txt"


def ceiling(flavour: str, arch: str, text: str) -> int | None:
    """The budget in MiB for flavour and arch; the last matching line wins."""
    found = None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[0].startswith("#"):
            continue
        if parts[0] == flavour and parts[1] == arch:
            found = int(parts[2])
    return found


def main(argv: list[str]) -> int:
    repo.enter_root()
    flavour = argv[0] if argv else "erofs"
    if flavour not in ("erofs", "oci"):
        print("usage: rootfs-size.py [erofs|oci] [report]", file=sys.stderr)
        return 2
    given = argv[1] if len(argv) > 1 else f"output/rootfs-size-{flavour}.txt"
    arch = repo.normalize_arch(os.environ.get("ARCH"))

    if not Path(given).is_file():
        print(f"error: no size report at {given}", file=sys.stderr)
        print(
            "       image/build-rootfs.sh writes one per flavour into output/; "
            "build the image first",
            file=sys.stderr,
        )
        return 1

    # `total` is the apparent size of the tree; the rest is what that tree costs in the
    # container it ends up in, a different question per flavour: `disk` for what the
    # compressed EROFS image comes to, `archive` for what a registry stores and a pull moves.
    r = read(Path(given))
    if r.total <= 0:
        print(f"error: {given} has no total", file=sys.stderr)
        return 1

    # An image with no line is an image nothing is watching, which is the state this
    # check exists to make impossible: an error rather than a pass, and the message is
    # the line to add.
    budget_mib = ceiling(flavour, arch, Path(BUDGET).read_text())
    if budget_mib is None:
        print(
            f"error: {BUDGET} has no line for {flavour}/{arch}, so nothing is capping that "
            "image.\n"
            f"       It measures {mib(r.total)} MiB today. Add a line — the measurement plus\n"
            "       about 8% of headroom, which is how the others were set:\n"
            "\n"
            f"           {flavour}    {arch}    {r.total // 1024 // 1024 * 108 // 100}",
            file=sys.stderr,
        )
        return 1
    limit = budget_mib * 1024 * 1024
    percent = r.total * 100 // limit

    print(
        f"image size ({flavour}, {arch}): {mib(r.total)} MiB of a {budget_mib} MiB budget "
        f"({percent}%)"
    )
    if r.disk > 0:
        print(f"  on disk: {mib(r.disk)} MiB of compressed EROFS image")
    if r.archive > 0:
        print(f"  archive: {mib(r.archive)} MiB of gzipped layer, config and manifest")
    print()
    print("  where it is:")
    print(f"    {'MiB':>8}  directory")
    for n, path in r.dirs:
        print(f"    {mib(n):>8}  {path}")
    print()
    print("  largest files:")
    for n, path in r.files:
        print(f"    {mib(n):>8}  {path}")

    cost = ""
    if r.disk > 0:
        cost = f"{mib(r.disk)} MiB as a compressed EROFS image."
    if r.archive > 0:
        cost = f"{mib(r.archive)} MiB as a gzipped OCI archive."

    s = Report.summary_only()
    s.lines(
        [
            f"## Image size — {flavour}, {arch}",
            "",
            f"**{mib(r.total)} MiB** of a **{budget_mib} MiB** budget ({percent}%). {cost}",
            "",
            "| directory | MiB |",
            "| --- | ---: |",
            *(f"| `{path}` | {mib(n)} |" for n, path in r.dirs),
            "",
            "<details><summary>Largest files</summary>",
            "",
            "| file | MiB |",
            "| --- | ---: |",
            *(f"| `{path}` | {mib(n)} |" for n, path in r.files),
            "",
            "</details>",
        ]
    )

    if r.total > limit:
        print()
        sys.stdout.flush()
        print(
            f"error: the {flavour} image is {mib(r.total)} MiB, over its {budget_mib} MiB "
            f"budget on {arch}\n"
            f"       by {mib(r.total - limit)} MiB.\n"
            "       Either find what grew in the breakdown above and take it back out, or —\n"
            f"       if this is growth you wanted — raise the '{flavour} {arch}' line in "
            f"{BUDGET} in\n"
            "       the same commit that caused it. Raising it silently later is the thing "
            "this\n"
            "       check exists to prevent.",
            file=sys.stderr,
        )
        return 1

    # A ceiling only controls anything while it is close to the floor. Left far above the
    # real size, after a large deliberate removal say, it stops being a budget and starts
    # being decoration, so say so rather than quietly passing forever.
    if percent < 75:
        print()
        print(
            f"note: the image is only {percent}% of its budget. Consider lowering the "
            f"'{flavour}\n"
            f"      {arch}' line in {BUDGET} to around {r.total // 1024 // 1024 + 5} MiB "
            "— a ceiling\n"
            "      this far above the floor will not catch anything."
        )
    return 0


if __name__ == "__main__":
    sys.exit(run(main, sys.argv[1:]))
