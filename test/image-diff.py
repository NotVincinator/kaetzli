#!/usr/bin/env python3
# What this build changes in the image against main: packages, paths and size.
#
# The code is python/src/kaetzli/image_diff.py, run in python/'s venv (python/README.md).
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
import launch  # noqa: E402

launch.module("kaetzli.image_diff")
