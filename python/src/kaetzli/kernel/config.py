"""Reading a kernel .config, and the symbol lists in test/ that the checks hold it to."""

from __future__ import annotations

import re
from pathlib import Path

_SET = re.compile(r"(CONFIG_[A-Z0-9_]+)=(.*)")
_NOT_SET = re.compile(r"# (CONFIG_[A-Z0-9_]+) is not set")
_ARCH = re.compile(r"# Linux/([a-z0-9_]*) ")


def path_of(arg: str) -> Path:
    """A .config as given, or a tree's boot/config (where packages/kernel stages it)."""
    p = Path(arg)
    return p / "boot" / "config" if p.is_dir() else p


def lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="surrogateescape").splitlines()


def values(path: Path) -> dict[str, str]:
    """Every symbol the config defines, with "n" for one it says is not set."""
    out: dict[str, str] = {}
    for line in lines(path):
        if m := _SET.fullmatch(line):
            out[m[1]] = m[2]
        elif m := _NOT_SET.fullmatch(line):
            out[m[1]] = "n"
    return out


def settings(path: Path) -> set[str]:
    """Every symbol that is set, as NAME=value: "is not set" is not a value."""
    return {line for line in lines(path) if _SET.fullmatch(line)}


def arch(path: Path) -> str | None:
    """The architecture in the header Kconfig writes: x86, arm64."""
    for line in lines(path):
        if m := _ARCH.match(line):
            return m[1]
    return None


def symbol_list(path: Path) -> list[tuple[str | None, str, str]]:
    """(section, symbol, why) for each line of a list in test/: a symbol without CONFIG_,
    then the reason; `[name]` starts a section, and before any the section is None."""
    entries: list[tuple[str | None, str, str]] = []
    section: str | None = None
    for line in lines(path):
        if line.startswith("#") or not line.strip():
            continue
        if line.startswith("[") and line.rstrip().endswith("]"):
            section = line.strip()[1:-1]
            continue
        symbol, _, why = line.strip().partition(" ")
        entries.append((section, symbol, why.strip()))
    return entries
