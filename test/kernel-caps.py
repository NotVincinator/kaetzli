#!/usr/bin/env python3
# Assert the kernel can actually run a container — and boot on the VMMs this image
# targets, be a Kubernetes node, and be traced by the debug extension:
#
#     ./test/kernel-caps.py [rootfs]      # default rootfs/, reads rootfs/boot/config
#
# The code is python/src/kaetzli/kernel/caps.py, run in python/'s venv (python/README.md).
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
import launch  # noqa: E402

launch.module("kaetzli.kernel.caps")
