#!/usr/bin/env python3
# Hold the amd64 and arm64 kernels to the same features:
#
#     ./test/kernel-parity.py <amd64 config> <arm64 config>    # each a .config, or a tree with boot/config
#
# The code is python/src/kaetzli/kernel/parity.py, run in python/'s venv (python/README.md).
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
import launch  # noqa: E402

launch.module("kaetzli.kernel.parity")
