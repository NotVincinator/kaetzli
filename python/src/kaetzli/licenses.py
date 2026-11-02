"""Every package declares a license, and every license is one this image will carry:

    ./test/check-licenses.py

The declaration is `LICENSE=` in the package's env.sh, as an SPDX expression, parsed by
license-expression. The list of acceptable identifiers is test/dfsg-licenses.txt, and
the bar is the Debian Free Software Guidelines — see that file for why. Which of them
are exceptions, valid only after WITH, is SPDX's list as license-expression carries it.

This is cheap and needs nothing built, which is why it is its own workflow rather than a
step in the middle of CI: a package whose license is wrong should be answered in seconds,
on the pull request that adds it, not after forty minutes of compiling.

What it checks is that a declaration exists, is an expression, and is free. What it
cannot check is that the declaration is *true* — nothing here opens the tarball. That is
a packaging step, done once against the COPYING the tarball ships, and re-checked when a
version bump crosses a relicensing.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import license_expression as le

from kaetzli import repo

ALLOWLIST = "test/dfsg-licenses.txt"
OPERATORS = ("AND", "OR", "WITH")


def allowlist(path: Path) -> list[str]:
    """The identifiers, in file order: the first word of each line, comments removed."""
    ids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        words = line.split("#", 1)[0].split()
        if words and words[0] not in ids:
            ids.append(words[0])
    return ids


@cache
def _spdx() -> le.Licensing:
    return le.get_spdx_licensing()


def is_exception(identifier: str) -> bool:
    """SPDX's own list says so; a LicenseRef- is a license."""
    known = _spdx().known_symbols.get(identifier)
    return bool(known and known.is_exception)


@dataclass
class Verdict:
    not_allowed: list[str] = field(default_factory=list)
    invalid: str | None = None


def judge(expression: str, allowed: list[str]) -> Verdict:
    """What is wrong with one LICENSE: an identifier not allowed, or not an expression."""
    words = re.split(r"[\s()]+", expression)
    lower = [w for w in words if w.upper() in OPERATORS and w not in OPERATORS]
    if lower:
        return Verdict(invalid=f"operators are upper case: {' '.join(lower)}")

    licensing = le.Licensing()
    try:
        parsed = licensing.parse(expression, validate=False, strict=False)
        symbols = licensing.license_symbols(parsed, unique=False, decompose=False)
    except (le.ExpressionError, IndexError) as e:
        why = str(e) if isinstance(e, le.ExpressionError) else "not an SPDX expression"
        return Verdict(invalid=why)

    # (identifier, whether it stands where an exception goes)
    uses: list[tuple[str, bool]] = []
    for s in symbols:
        if isinstance(s, le.LicenseWithExceptionSymbol):
            uses += [(s.license_symbol.key, False), (s.exception_symbol.key, True)]
        else:
            uses.append((s.key, False))

    for key, _ in uses:
        if len(key.split()) > 1:
            a, b = key.split()[:2]
            return Verdict(invalid=f"no operator between {a} and {b}")

    not_allowed: list[str] = []
    for key, _ in uses:
        if key not in allowed and key not in not_allowed:
            not_allowed.append(key)
    if not_allowed:
        return Verdict(not_allowed=not_allowed)

    for key, after_with in uses:
        if after_with and not is_exception(key):
            return Verdict(invalid=f"{key} is a license, not an exception")
        if not after_with and is_exception(key):
            return Verdict(invalid=f"{key} is an exception, only valid after WITH")
    return Verdict()


def _err(*lines: str) -> None:
    for line in lines:
        print(line, file=sys.stderr)


def check(declared: dict[str, str], allowlist_path: str = ALLOWLIST) -> int:
    """Each package's LICENSE against the allowlist; the table on stdout, errors on stderr."""
    allowed = allowlist(Path(allowlist_path))
    if not allowed:
        _err(f"error: {allowlist_path} lists no licenses")
        return 1

    undeclared: list[str] = []
    invalid: list[str] = []
    rejected: list[str] = []
    for pkg, license_ in sorted(declared.items()):
        if not license_:
            print(f"  {pkg:<12} (no LICENSE declared)")
            undeclared.append(pkg)
            continue
        v = judge(license_, allowed)
        if v.invalid:
            print(f"  {pkg:<12} {license_:<52} NOT VALID: {v.invalid}")
            invalid.append(pkg)
        elif v.not_allowed:
            print(f"  {pkg:<12} {license_:<52} NOT ALLOWED: {' '.join(v.not_allowed)}")
            rejected.append(pkg)
        else:
            print(f"  {pkg:<12} {license_}")

    print()
    sys.stdout.flush()

    if undeclared:
        _err(
            f"error: no LICENSE in packages/{{{' '.join(undeclared)}}}/env.sh",
            "       Add one, as an SPDX expression describing what the tarball ships:",
            "",
            '           LICENSE="GPL-3.0-or-later"',
            '           LICENSE="BSD-3-Clause OR GPL-2.0-only"      # upstream offers a choice',
            '           LICENSE="LGPL-2.1-or-later AND GPL-2.0-or-later"'
            "  # library and tools differ",
            "",
            "       Read it off the tarball's COPYING rather than assuming.",
        )
    if invalid:
        _err(
            f"error: {len(invalid)} package(s) declare a LICENSE that is not an SPDX expression:",
            f"       {' '.join(invalid)}",
            "",
            "       Identifiers joined by AND, OR and WITH, parenthesised where they group,",
            "       with an exception only after WITH and nowhere else.",
        )
    if rejected:
        _err(
            f"error: {len(rejected)} package(s) declare a license that is not in {allowlist_path}:",
            f"       {' '.join(rejected)}",
            "",
            "       Either the identifier is misspelled, or this is a license nobody has",
            "       decided about yet. The second case is a real decision: the bar is the",
            "       Debian Free Software Guidelines, so a license Debian ships in main can",
            f"       be added to {allowlist_path}, and one that only exists in non-free means the",
            "       package does not belong in this image.",
        )
    if undeclared or invalid or rejected:
        return 1

    print(
        f"all {len(allowed)} allowed licenses, {len(declared)} packages,"
        " nothing undeclared or non-free"
    )
    return 0


def main(argv: list[str]) -> int:
    if argv:
        _err("usage: test/check-licenses.py")
        return 2
    repo.enter_root()
    return check(repo.env_get_all("LICENSE"))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
