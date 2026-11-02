#!/bin/bash
# requirements.txt from requirements.in, compiled on Python 3.12, the baseline: the
# Python workflow recompiles the same way and fails on any difference, and Dependabot
# reads the version from the header. In a python:3.12 container, so it does not depend
# on the host having a 3.12; pip-tools is the one pinned in the lock it is updating.
#
#     python/lock.sh                       # requirements.in changed: lock what it says
#     python/lock.sh --upgrade-package X   # move one dependency to its newest release
#
# Pins already in requirements.txt are kept unless asked otherwise, so a release younger
# than two weeks only arrives through Dependabot's cooldown or an explicit upgrade.
set -euo pipefail
cd "$(dirname "$0")"
baseline=$(cat .python-version)
podman run --rm --pull=newer -v "$PWD:/p:Z" -w /p "docker.io/library/python:$baseline-slim" \
    sh -euc '
        python -m venv /tmp/v
        /tmp/v/bin/pip install --quiet --disable-pip-version-check --no-input \
            --require-hashes --no-deps -r requirements.txt
        exec /tmp/v/bin/pip-compile "$@" requirements.in
    ' lock "$@"
