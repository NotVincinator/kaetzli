#!/usr/bin/env python3
# Is the Debian snapshot both images are pinned to still current?
#
#     ./tools/check-snapshot.py           # human readable
#     ./tools/check-snapshot.py --json    # the shape update-packages.yml consumes
#
# The code is python/src/kaetzli/updates/snapshot.py, run in python/'s venv (python/README.md).
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
import launch  # noqa: E402

launch.module("kaetzli.updates.snapshot")
