#!/usr/bin/env python3
# Undefined symbols nothing in a binary's NEEDED closure defines.
#
# The code is python/src/kaetzli/elf/resolution.py, run in python/'s venv (python/README.md).
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
import launch  # noqa: E402

launch.module("kaetzli.elf.resolution")
