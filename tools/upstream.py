#!/usr/bin/env python3
# Print the latest version a package's upstream has released:
#
#     tools/upstream.py coreutils
#     9.8
#
# The code is python/src/kaetzli/updates/upstream.py, run in python/'s venv (python/README.md).
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
import launch  # noqa: E402

launch.module("kaetzli.updates.upstream")
