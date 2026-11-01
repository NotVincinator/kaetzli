"""The size report image/build-rootfs.sh writes per flavour (output/rootfs-size-<f>.txt),
and the numbers every size script prints from it.

    # comment
    total <bytes>           apparent size of the assembled tree
    disk <bytes>            the compressed EROFS image (erofs only)
    archive <bytes>         the OCI archive (oci only)
    dir <bytes> <path>      du -b to depth 2, 64 KiB and up, largest first
    file <bytes> <path>     the 25 largest files
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


def mib(n: int) -> str:
    """Bytes as MiB to a tenth, rounded half up: tools/lib.sh's mib."""
    tenths = (n * 10 + 524288) // 1048576
    return f"{tenths // 10}.{tenths % 10}"


MINUS = "\u2212"  # a real minus sign, which a table sets as wide as the plus


def delta(d: int) -> str:
    """+1.2, MINUS 1.2 or 0.0."""
    if d > 0:
        return f"+{mib(d)}"
    if d < 0:
        return f"{MINUS}{mib(-d)}"
    return "0.0"


@dataclass
class SizeReport:
    total: int = 0
    disk: int = 0
    archive: int = 0
    dirs: list[tuple[int, str]] = field(default_factory=list)
    files: list[tuple[int, str]] = field(default_factory=list)

    def dir_sizes(self) -> dict[str, int]:
        return {path: n for n, path in self.dirs}


def parse(text: str) -> SizeReport:
    r = SizeReport()
    for line in text.splitlines():
        parts = line.split(None, 2)
        if not parts or parts[0].startswith("#") or len(parts) < 2:
            continue
        kind, n = parts[0], int(parts[1])
        if kind in ("total", "disk", "archive"):
            setattr(r, kind, n)
        elif kind == "dir" and len(parts) == 3:
            r.dirs.append((n, parts[2]))
        elif kind == "file" and len(parts) == 3:
            r.files.append((n, parts[2]))
    return r


def read(path: Path) -> SizeReport:
    return parse(Path(path).read_text())


def read_or_empty(path: Path) -> SizeReport:
    """A report that is not there counts as zero: an expired or older artifact."""
    p = Path(path)
    return read(p) if p.is_file() else SizeReport()
