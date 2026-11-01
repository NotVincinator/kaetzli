"""Run a kaetzli module in the project's virtualenv: what every Python entry point calls.

    #!/usr/bin/env python3
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
    import launch
    launch.module("kaetzli.cve.scan")

The entry point runs on whatever python3 the host has, so this file is stdlib only and
does one thing: exec `uv run --locked` on python/, which creates or updates python/.venv
from uv.lock and runs the module there. Nothing is ever installed outside that venv.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent


def argv(module: str, args: list[str]) -> list[str]:
    return [
        "uv", "run", "--quiet", "--locked", "--project", str(PROJECT),
        "python", "-m", module, *args,
    ]  # fmt: skip


def module(name: str, args: list[str] | None = None, execvp=os.execvp, which=shutil.which):
    if not which("uv"):
        print(
            "error: uv is needed to run the Python tools (python/README.md):\n"
            "       https://docs.astral.sh/uv/getting-started/installation/",
            file=sys.stderr,
        )
        sys.exit(2)
    a = argv(name, sys.argv[1:] if args is None else args)
    execvp(a[0], a)
