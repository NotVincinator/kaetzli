#!/usr/bin/env python3
# Shared libraries a binary in the tree needs and the tree does not ship.
#
# The code is python/src/kaetzli/elf/deps.py, run in python/'s venv (python/README.md).
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
import launch  # noqa: E402

launch.module("kaetzli.elf.deps")
