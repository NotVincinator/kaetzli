#!/usr/bin/env python3
# What the container flavour leaves out of the disk image, and whether the rest links.
#
# The code is python/src/kaetzli/size/trim.py, run in python/'s venv (python/README.md).
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
import launch  # noqa: E402

launch.module("kaetzli.size.trim")
