#!/usr/bin/env python3
# Our container image against debian-slim, the image it would otherwise replace.
#
# The code is python/src/kaetzli/size/slim.py, run in python/'s venv (python/README.md).
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
import launch  # noqa: E402

launch.module("kaetzli.size.slim")
