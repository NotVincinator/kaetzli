"""What a report script prints: to stdout, and to the job summary when there is one.

Reports here never fail a build. Anything that stops one early (no gh, no data, an
unreachable source) raises Note, which `run` prints in italics and turns into exit 0.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import TextIO

_BARS = "▁▂▃▄▅▆▇█"


def sparkline(values: Sequence[float]) -> str:
    """The series' shape, scaled to its own range; flat is the middle bar."""
    if not values:
        return "—"
    lo, hi = min(values), max(values)
    if hi == lo:
        return _BARS[3] * len(values)
    return "".join(_BARS[int((v - lo) * 7 / (hi - lo))] for v in values)


class Report:
    """Lines to stdout, and appended to $GITHUB_STEP_SUMMARY when it is set.

    A job summary has to be text (CLAUDE.md): markdown tables, no mermaid.
    """

    def __init__(self, stdout: TextIO | None = None, summary_path: Path | None = None):
        self.stdout = stdout
        self.summary_path = summary_path

    @classmethod
    def from_env(cls) -> Report:
        path = os.environ.get("GITHUB_STEP_SUMMARY") or None
        return cls(stdout=None, summary_path=Path(path) if path else None)

    @classmethod
    def quiet(cls) -> Report:
        """Writes nowhere: a report run for its files alone."""
        return cls(stdout=_Discard(), summary_path=None)

    def out(self, line: str = "") -> None:
        print(line, file=self.stdout or sys.stdout)
        if self.summary_path:
            with open(self.summary_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def lines(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.out(line)


class _Discard:
    def write(self, _s: str) -> int:
        return 0

    def flush(self) -> None:
        pass


class Note(Exception):
    """Stop here, say why in italics, and exit 0."""

    def __init__(self, message: str, report: Report | None = None):
        super().__init__(message)
        self.message = message
        self.report = report

    def __str__(self) -> str:
        return f"_{self.message}_"


def run(main: Callable[[list[str]], int | None], argv: list[str]) -> int:
    try:
        return main(argv) or 0
    except Note as n:
        (n.report or Report()).out(str(n))
        return 0


def note(message: str) -> None:
    """A note on stderr that does not stop anything."""
    print(f"_{message}_", file=sys.stderr)


def _tsv_field(value: object) -> str:
    if value is None or value is False:
        return ""
    s = str(value)
    return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def tsv(fields: Iterable[object]) -> str:
    """One row, escaped as jq's @tsv does; null and false are empty."""
    return "\t".join(_tsv_field(f) for f in fields)
