#!/usr/bin/env python3
# How the image size has moved over the last builds on main.
#
# The code is python/src/kaetzli/size/history.py, run in python/'s venv (python/README.md).
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
import launch  # noqa: E402

launch.module("kaetzli.size.history")
