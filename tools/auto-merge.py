#!/usr/bin/env python3
# Merge the pull requests update-packages.yml opened, one at a time, each only after CI
# has passed on exactly the commit that lands on main:
#
#     ./tools/auto-merge.py        # what .github/workflows/auto-merge.yml runs
#     ./tools/auto-merge.py -n     # say what would happen, touch nothing (works locally)
#
# The code is python/src/kaetzli/automerge.py, run in python/'s venv (python/README.md).
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
import launch  # noqa: E402

launch.module("kaetzli.automerge")
