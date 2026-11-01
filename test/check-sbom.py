#!/usr/bin/env python3
# Does the SBOM this build produced actually say what is in the image?
#
#     ./test/check-sbom.py                       # both flavours from output/
#     ./test/check-sbom.py output/sbom-oci.json  # one document
#
# The code is python/src/kaetzli/sbom_check.py, run in python/'s venv (python/README.md).
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
import launch  # noqa: E402

launch.module("kaetzli.sbom_check")
