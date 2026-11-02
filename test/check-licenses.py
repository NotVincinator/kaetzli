#!/usr/bin/env python3
# Every package declares a license, and every license is one this image will carry:
#
#     ./test/check-licenses.py
#
# The code is python/src/kaetzli/licenses.py, run in python/'s venv (python/README.md).
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
import launch  # noqa: E402

launch.module("kaetzli.licenses")
