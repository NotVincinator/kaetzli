#!/usr/bin/env python3
# Compare the version each package is pinned to against what upstream has released:
#
#     ./tools/check-updates.py              # every package
#     ./tools/check-updates.py bash glibc   # only these
#     ./tools/check-updates.py --json       # machine-readable, for the update workflow
#
# The code is python/src/kaetzli/updates/check.py, run in python/'s venv (python/README.md).
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
import launch  # noqa: E402

launch.module("kaetzli.updates.check")
