"""What the three library checks read from a tree: each ELF file's dynamic section,
version tables and dynamic symbols, and the tree's symlinks.

    deps        check-rootfs-deps.py: is every NEEDED library in the tree?
    versions    check-symbol-versions.py: does it define the versions a binary asks for?
    resolution  check-symbol-resolution.py: does the NEEDED closure define every symbol?

pyelftools reads the tables themselves, so there is no readelf text to misparse. The bash
versions split readelf's rows into columns, and on arm64 a `[VARIANT_PCS]` beside the
visibility moved every column after it by one: libmvec's vector functions were read as
definitions of their section number, and an undefined one would have been a definition
of `UND`.

Every regular file is opened (`find -type f`: not a symlink, which is counted separately);
one that is not ELF, or that pyelftools cannot read, is not ELF here either, as readelf's
errors went to /dev/null. The files are read in parallel, one process per CPU.
"""

from __future__ import annotations

import os
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from elftools.elf.dynamic import DynamicSection
from elftools.elf.elffile import ELFFile
from elftools.elf.gnuversions import GNUVerDefSection, GNUVerNeedSection
from elftools.elf.sections import SymbolTableSection

_MAGIC = b"\x7fELF"


@dataclass
class Elf:
    path: str  # relative to the tree's root
    soname: str | None  # DT_SONAME, if it has one
    needed: list[str] = field(default_factory=list)
    # The versions it defines (the first name of each definition, the BASE one being its
    # SONAME), and the ones it needs, as (NEEDED name, version).
    defines: list[str] = field(default_factory=list)
    needs: list[tuple[str, str]] = field(default_factory=list)
    has_dynsym: bool = False
    defined: frozenset[str] = frozenset()
    undefined: list[str] = field(default_factory=list)  # not weak, in table order

    @property
    def name(self) -> str:
        """What the loader can know it by: its SONAME, or its file name when it has none."""
        return self.soname or self.path.rsplit("/", 1)[-1]


def read(root: Path, rel: str, symbols: bool = False) -> Elf | None:
    """One file, or None when it is not ELF."""
    path = root / rel
    try:
        with open(path, "rb") as f:
            if f.read(4) != _MAGIC:
                return None
            f.seek(0)
            return _read(ELFFile(f), rel, symbols)
    except Exception:
        return None


def _read(elf: ELFFile, rel: str, symbols: bool) -> Elf:
    e = Elf(path=rel, soname=None)
    for section in elf.iter_sections():
        if isinstance(section, DynamicSection):
            for tag in section.iter_tags():
                if tag.entry.d_tag == "DT_NEEDED":
                    e.needed.append(tag.needed)
                elif tag.entry.d_tag == "DT_SONAME":
                    e.soname = tag.soname
        elif isinstance(section, GNUVerDefSection):
            for _verdef, aux in section.iter_versions():
                first = next(iter(aux), None)
                if first is not None:
                    e.defines.append(first.name)
        elif isinstance(section, GNUVerNeedSection):
            for verneed, aux in section.iter_versions():
                e.needs.extend((verneed.name, a.name) for a in aux)
        elif symbols and isinstance(section, SymbolTableSection):
            if section["sh_type"] != "SHT_DYNSYM":
                continue
            e.has_dynsym = True
            defined = set()
            for sym in section.iter_symbols():
                if not sym.name:
                    continue
                if sym["st_shndx"] == "SHN_UNDEF":
                    if sym["st_info"]["bind"] != "STB_WEAK":
                        e.undefined.append(sym.name)
                else:
                    defined.add(sym.name)
            e.defined = frozenset(defined)
    return e


def regular_files(root: Path) -> list[str]:
    """Every regular file under root, relative to it, in byte order."""
    out = []
    for d, dirs, files in os.walk(root):
        dirs.sort()
        rel = os.path.relpath(d, root)
        for name in files:
            p = os.path.join(d, name)
            if not os.path.islink(p) and os.path.isfile(p):
                out.append(name if rel == "." else f"{rel}/{name}")
    return sorted(out)


def symlinks(root: Path) -> list[str]:
    """Every symlink under root, relative to it, in byte order."""
    out = []
    for d, dirs, files in os.walk(root):
        rel = os.path.relpath(d, root)
        for name in dirs + files:
            if os.path.islink(os.path.join(d, name)):
                out.append(name if rel == "." else f"{rel}/{name}")
    return sorted(out)


def _chunk(args: tuple[str, list[str], bool]) -> list[Elf]:
    root, rels, symbols = args
    return [e for rel in rels if (e := read(Path(root), rel, symbols)) is not None]


def scan(root: Path, symbols: bool = False, jobs: int | None = None) -> list[Elf]:
    """Every ELF file under root, in byte order of its path."""
    rels = regular_files(root)
    jobs = jobs or os.cpu_count() or 1
    if jobs == 1 or len(rels) < 64:
        return _chunk((str(root), rels, symbols))
    size = 40
    chunks = [(str(root), rels[i : i + size], symbols) for i in range(0, len(rels), size)]
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        return [e for part in pool.map(_chunk, chunks) for e in part]


def tree_or_exit(argv: list[str]) -> tuple[str, Path]:
    """The tree a check was given (rootfs by default), as said and as a path."""
    given = argv[0] if argv else "rootfs"
    if not Path(given).is_dir():
        print(f"error: no such directory: {given}", file=sys.stderr)
        sys.exit(1)
    return given, Path(given)


def head(items: list[str], n: int, prefix: str) -> list[str]:
    """The first n, then how many more: how every finding lists what it names."""
    out = [f"{prefix}{x}" for x in items[:n]]
    if len(items) > n:
        out.append(f"      ... and {len(items) - n} more")
    return out
