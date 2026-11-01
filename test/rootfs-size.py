#!/usr/bin/env python3
# What an assembled image weighs, and whether that is still allowed.
#
# The code is python/src/kaetzli/size/budget.py, run in python/'s venv (python/README.md).
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
import launch  # noqa: E402

launch.module("kaetzli.size.budget")
