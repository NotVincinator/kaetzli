"""What the container flavour leaves out of the disk image, and whether what is left still
links: the OCI subtractions in image/build-rootfs.sh, made reviewable.

    ./test/oci-trim.py [output-dir]          # a summary by area
    FULL=1 ./test/oci-trim.py [output-dir]   # every path

Nothing here re-derives the subtractions. It compares the manifests the assembly writes
of each finished tree (rootfs-files-erofs.txt, rootfs-files-oci.txt), so it shows the
whole difference, the trim's side effects included:

  removed   paths in the disk image and not in the container, by area (the first three
            path components), with the shared libraries among them named
  added     paths only the container has (its /home/user, the /var the disk image
            empties for its tmpfs)
  links     test/check-rootfs-deps.py run on the container's own layer, unpacked from
            kaetzli-oci.tar: the evidence that no binary left behind needs a library the
            subtractions deleted. build-rootfs.sh's own consumer guards (glib and pcre2,
            libudev) fail the assembly before this; this covers everything else.

Fails only when the links check does, or an input is missing. CI runs it in the rootfs
job and puts it in the job summary.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from pathlib import Path
from typing import TextIO

from kaetzli import repo
from kaetzli.report import run
from kaetzli.size.sizes import mib, read_or_empty

_SHARED_LIBRARY = re.compile(r"(^|/)lib[^/]*\.so(\.[0-9.]+)?$")


def manifest(path: Path) -> list[str]:
    """A rootfs-files manifest's paths, in byte order (LC_ALL=C sort)."""
    return sorted(x for x in Path(path).read_text().splitlines() if not x.startswith("#"))


def tops(paths: list[str]) -> list[str]:
    """The topmost path of each subtree: `usr/lib/systemd` is one entry, not four hundred."""
    have = set(paths)
    out = []
    for p in paths:
        parts = p.split("/")
        if not any("/".join(parts[:i]) in have for i in range(1, len(parts))):
            out.append(p)
    return out


def areas(paths: list[str], limit: int = 25) -> list[tuple[int, str]]:
    """Paths per area, the first three components, most first."""
    n = Counter("/".join(p.split("/")[:3]) for p in paths)
    return sorted(((c, a) for a, c in n.items()), key=lambda x: (-x[0], x[1]))[:limit]


def shared_libraries(paths: list[str]) -> list[str]:
    return [p for p in paths if _SHARED_LIBRARY.search(p)]


def unpack_layer(archive: Path, tree: Path) -> None:
    """The container's tree, from its one layer: index.json -> manifest -> layer, read
    from the archive without unpacking it, then GNU tar for the tree itself."""
    with tarfile.open(archive) as t:

        def blob(digest: str) -> bytes | None:
            name = "blobs/sha256/" + digest.removeprefix("sha256:")
            try:
                f = t.extractfile(name)
            except KeyError:
                return None
            return f.read() if f else None

        index = json.loads(t.extractfile("index.json").read())
        man = json.loads(blob(index["manifests"][0]["digest"]) or b"{}")
        layer = blob(man.get("layers", [{}])[0].get("digest", ""))
    if layer is None:
        raise FileNotFoundError(f"no layer blob in {archive}")
    subprocess.run(
        ["tar", "xz", "-C", str(tree), "--no-same-owner", "--no-same-permissions",
         "--exclude=./dev/*"],
        input=layer, check=True,
    )  # fmt: skip


def check_deps(tree: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(repo.ROOT / "test" / "check-rootfs-deps.py"), str(tree)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False,
        env=dict(os.environ, LC_ALL="C"),
    )  # fmt: skip


def _indent(lines: list[str]) -> list[str]:
    return [f"  {x}" for x in lines]


def trim(out_dir: Path, stdout: TextIO, full: bool = False) -> int:
    erofs = out_dir / "rootfs-files-erofs.txt"
    oci = out_dir / "rootfs-files-oci.txt"
    archive = out_dir / "kaetzli-oci.tar"
    for f in (erofs, oci, archive):
        if not f.is_file():
            print(f"error: no {f} (./tools/build-image.sh writes it)", file=sys.stderr)
            return 1

    def say(*lines: str) -> None:
        for line in lines:
            print(line, file=stdout)

    disk, container = manifest(erofs), manifest(oci)
    in_disk, in_container = set(disk), set(container)
    removed = [p for p in disk if p not in in_container]
    added = [p for p in container if p not in in_disk]
    removed_tops = tops(removed)

    say(f"OCI image against the disk image ({len(disk)} and {len(container)} paths)")
    size = {f: read_or_empty(out_dir / f"rootfs-size-{f}.txt").total for f in ("erofs", "oci")}
    if size["erofs"] and size["oci"]:
        say(f"  tree size: {mib(size['erofs'])} MiB disk, {mib(size['oci'])} MiB container")
    say(
        f"  removed:   {len(removed)} paths, in {len(removed_tops)} subtrees or files",
        f"  added:     {len(added)} paths",
        "",
        "removed, by area (paths):",
        *(f"{n:6d}  {a}" for n, a in areas(removed)),
        "",
        "shared libraries removed:",
        *(_indent(shared_libraries(removed)) or ["  (none)"]),
        "",
        "added (only in the container):",
        *(_indent(tops(added)) or ["  (none)"]),
    )
    if full:
        say("", "every removed path:", *_indent(removed))

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as work:
        tree = Path(work) / "tree"
        tree.mkdir()
        try:
            unpack_layer(archive, tree)
        except FileNotFoundError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        say("", "links: test/check-rootfs-deps.py on the container's layer")
        p = check_deps(tree)
        lines = p.stdout.splitlines()
        if p.returncode == 0:
            say(*_indent(lines[-1:]))
            return 0
        say(*_indent(lines))
        stdout.flush()
        print(
            "error: a binary in the container needs a library it does not ship; see above",
            file=sys.stderr,
        )
        return 1


def main(argv: list[str]) -> int:
    repo.enter_root()
    out_dir = Path(argv[0] if argv else "output")
    return trim(out_dir, sys.stdout, full=os.environ.get("FULL", "0") == "1")


if __name__ == "__main__":
    sys.exit(run(main, sys.argv[1:]))
