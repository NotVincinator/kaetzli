#!/usr/bin/env python3
# How far the builder's development headers are from the libraries we ship:
#
#     ./tools/header-skew.py
#
# The code is python/src/kaetzli/header_skew.py, run in python/'s venv (python/README.md).
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
import launch  # noqa: E402

launch.module("kaetzli.header_skew")
