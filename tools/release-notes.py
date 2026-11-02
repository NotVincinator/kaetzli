#!/usr/bin/env python3
# Print a best-effort release-notes URL for a package and version:
#
#     tools/release-notes.py <package> <version>
#
# The code is python/src/kaetzli/updates/release_notes.py, run in python/'s venv (python/README.md).
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
import launch  # noqa: E402

launch.module("kaetzli.updates.release_notes")
