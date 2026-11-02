#!/usr/bin/env python3
# What a kernel build changed about the kernel, as a list a person can read:
#
#     ./test/kernel-config-diff.py <old .config> <new .config> [<new kernel source>]
#
# The code is python/src/kaetzli/kernel/config_diff.py, run in python/'s venv (python/README.md).
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
import launch  # noqa: E402

launch.module("kaetzli.kernel.config_diff")
