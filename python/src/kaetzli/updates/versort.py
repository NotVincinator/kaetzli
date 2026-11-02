"""GNU `sort -V`: gnulib's filevercmp, so versions order here as they did in the shell.

A trailing run of `.<letter>…` parts is a file suffix, compared only when the rest ties
(passt's 2026_01_20.a1b2c3d). What remains is compared as Debian's verrevcmp does: runs
of digits numerically, everything else by character, letters before other characters
and `~` before everything, even the end of the string. Two strings that still tie are
ordered by their bytes, which is sort's last resort, and `sort -u` keeps the first.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import cmp_to_key


def _order(c: str) -> int:
    if c.isdigit():
        return 0
    if c.isascii() and c.isalpha():
        return ord(c)
    if c == "~":
        return -1
    return ord(c) + 256


def _verrevcmp(a: str, b: str) -> int:
    i = j = 0
    while i < len(a) or j < len(b):
        first_diff = 0
        while (i < len(a) and not a[i].isdigit()) or (j < len(b) and not b[j].isdigit()):
            ac = 0 if i == len(a) else _order(a[i])
            bc = 0 if j == len(b) else _order(b[j])
            if ac != bc:
                return ac - bc
            i += 1
            j += 1
        while i < len(a) and a[i] == "0":
            i += 1
        while j < len(b) and b[j] == "0":
            j += 1
        while i < len(a) and j < len(b) and a[i].isdigit() and b[j].isdigit():
            if not first_diff:
                first_diff = ord(a[i]) - ord(b[j])
            i += 1
            j += 1
        if i < len(a) and a[i].isdigit():
            return 1
        if j < len(b) and b[j].isdigit():
            return -1
        if first_diff:
            return first_diff
    return 0


def _prefix(s: str) -> str:
    """s without its file suffix: gnulib's file_prefixlen."""
    prefixlen = i = 0
    n = len(s)
    while i < n:
        i += 1
        prefixlen = i
        while i + 1 < n and s[i] == "." and (_alpha(s[i + 1]) or s[i + 1] == "~"):
            i += 2
            while i < n and (_alpha(s[i]) or s[i].isdigit() or s[i] == "~"):
                i += 1
    return s[:prefixlen]


def _alpha(c: str) -> bool:
    return c.isascii() and c.isalpha()


def filevercmp(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return -1
    if not b:
        return 1
    # A leading ".": "." first, then "..", then other names that start with one.
    if a[0] == ".":
        if b[0] != ".":
            return -1
        if a == "." or b == ".":
            return (b == ".") - (a == ".")
        if a == ".." or b == "..":
            return (b == "..") - (a == "..")
    elif b[0] == ".":
        return 1
    pa, pb = _prefix(a), _prefix(b)
    result = _verrevcmp(pa, pb)
    if result or (pa == a and pb == b):
        return result
    return _verrevcmp(a, b)


def _cmp(a: str, b: str) -> int:
    return filevercmp(a, b) or (a > b) - (a < b)


def sort(values: Iterable[str], unique: bool = False) -> list[str]:
    """`sort -V`, or `sort -Vu`: of lines that compare equal, the first is kept."""
    if not unique:
        return sorted(values, key=cmp_to_key(_cmp))
    # -u turns off the last resort: equal lines keep their input order, and the first
    # of each run is the one printed.
    kept: list[str] = []
    for v in sorted(values, key=cmp_to_key(filevercmp)):
        if not kept or filevercmp(kept[-1], v) != 0:
            kept.append(v)
    return kept


def newer(current: str, latest: str) -> bool:
    """Whether latest sorts after current, so a downgrade is never proposed."""
    return current != latest and sort([current, latest])[-1] == latest
