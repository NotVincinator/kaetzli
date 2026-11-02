#!/usr/bin/env python3
# Symbol versions a binary needs that no library in the tree defines.
#
# The code is python/src/kaetzli/elf/versions.py, run in python/'s venv (python/README.md).
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
import launch  # noqa: E402

launch.module("kaetzli.elf.versions")
