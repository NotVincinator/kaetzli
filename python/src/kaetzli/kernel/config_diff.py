"""What a kernel build changed about the kernel, as a list a person can read:

    ./test/kernel-config-diff.py <old .config> <new .config> [<new kernel source>]

Prints nothing and exits 0 when the two agree. Never fails on a difference — this is a
report, not a gate; packages/kernel/build.sh is the gate, for what the fragments ask
for. What it cannot see is everything the fragments do *not* name: a new `default y`
driver, or one added to defconfig, is built in by a kernel bump with nothing here saying
so. CI's kernel job runs this against the kernel main last built and posts the result on
the pull request, so following the latest stable kernel stays automatic but not blind —
a hardware driver that slipped in is cleared in vm.config, in the bump's own pull
request.

With the kernel source, the report is split, using the new tree's Kconfig files:
  - options: symbols with a prompt, which is to say somebody's choice — the part to read
  - derived: prompt-less symbols (ARCH_HAS_*, HAVE_*, library helpers), counted only
and symbols whose value Kconfig computes from the toolchain are dropped altogether —
`$(cc-option …)`, the compiler and pahole versions, and the prompt-less symbols that
depend on those. A Debian snapshot bump moves them with nothing about the kernel having
changed, and a report that changes every time teaches people not to read it. Without
the source, every symbol is listed as an option.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from kaetzli.kernel import config

_ENTRY = re.compile(r"\s*(?:menu)?config\s+([A-Z0-9_]+)\s*")
_PROMPT = re.compile(r'\s+(?:bool|tristate|string|int|hex|prompt)\s+"')
_DEPENDS = re.compile(
    r"\s+(?:def_bool|def_tristate|def_int|def_hex|def_string|default|depends\s+on)\s"
)
_KEYWORD = re.compile(r"\s+[a-z_]+(?:\s+on)?")
_SYMBOL = re.compile(r"[A-Z][A-Z0-9_]+")

Classes = dict[str, tuple[bool, bool]]


def _entries(text: str):
    """(symbol, has a prompt, has a $( in a default or dependency, symbols referenced)
    for each Kconfig entry. An entry ends at the next one or at any line that starts in
    column 0 with a keyword (endmenu, source, if, choice, …). Help text is not told
    apart, so a `default` line in it counts: harmless, and what this always did."""
    sym, prompt, dollar, refs = None, False, False, []
    for line in text.splitlines():
        if m := _ENTRY.fullmatch(line):
            if sym:
                yield sym, prompt, dollar, refs
            sym, prompt, dollar, refs = m[1], False, False, []
            continue
        if re.match(r"[a-z]", line):
            if sym:
                yield sym, prompt, dollar, refs
            sym = None
            continue
        if sym is None:
            continue
        if _PROMPT.match(line):
            prompt = True
        if _DEPENDS.match(line):
            dollar = dollar or "$(" in line
            refs += _SYMBOL.findall(_KEYWORD.sub("", line, count=1))
    if sym:
        yield sym, prompt, dollar, refs


def classify(src: Path) -> Classes:
    """CONFIG_<symbol> → (prompted, toolchain) for every symbol any Kconfig defines.

    Toolchain symbols are the prompt-less ones with a `$(` in their defaults or
    dependencies, closed over the prompt-less symbols that depend on those —
    CC_HAS_COUNTED_BY is `default y if GCC_VERSION >= …`, with no `$(` of its own. A
    symbol with a prompt is never a toolchain symbol: whatever moved it, its changing is
    worth seeing. A symbol defined in several places is prompted if any one has a prompt.
    """
    prompted: set[str] = set()
    seeds: set[str] = set()
    refs: dict[str, set[str]] = {}
    known: set[str] = set()
    for path in sorted(src.rglob("Kconfig*")):
        if "Documentation" in path.relative_to(src).parts or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="surrogateescape")
        for sym, prompt, dollar, used in _entries(text):
            known.add(sym)
            if prompt:
                prompted.add(sym)
            if dollar:
                seeds.add(sym)
            refs.setdefault(sym, set()).update(used)

    toolchain = seeds - prompted
    grew = True
    while grew:
        grew = False
        for sym, used in refs.items():
            if sym not in toolchain and sym not in prompted and used & toolchain:
                toolchain.add(sym)
                grew = True
    return {f"CONFIG_{s}": (s in prompted, s in toolchain) for s in known}


def report(old: set[str], new: set[str], classes: Classes) -> list[str]:
    """The settings one config has and the other not, by symbol, a removal before an
    addition; then a count of the derived and toolchain ones, which are not listed. A
    symbol the new tree does not define at all (removed or renamed by the release) is
    listed: that is precisely the sort of change worth reading."""
    changes = [("-", s) for s in old - new] + [("+", s) for s in new - old]
    changes.sort(key=lambda c: (c[1].split("=", 1)[0], c[0] == "+"))
    out: list[str] = []
    derived = {"+": 0, "-": 0}
    toolchain = 0
    for sign, setting in changes:
        prompted, tc = classes.get(setting.split("=", 1)[0], (True, False))
        if tc:
            toolchain += 1
        elif not prompted:
            derived[sign] += 1
        else:
            out.append(f"{sign} {setting}")
    if derived["+"] + derived["-"]:
        out.append(
            f"# and {derived['+']} derived (prompt-less) settings added, {derived['-']} removed"
        )
    if toolchain:
        out.append(f"# and {toolchain} toolchain-derived settings changed, not shown")
    return out


def main(argv: list[str]) -> int:
    if not 2 <= len(argv) <= 3:
        print(
            "usage: test/kernel-config-diff.py <old .config> <new .config> [<new kernel source>]",
            file=sys.stderr,
        )
        return 2
    old, new = Path(argv[0]), Path(argv[1])
    for p in (old, new):
        if not p.is_file():
            print(f"error: no kernel config at {p}", file=sys.stderr)
            return 1
    classes = classify(Path(argv[2])) if len(argv) == 3 else {}
    for line in report(config.settings(old), config.settings(new), classes):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
