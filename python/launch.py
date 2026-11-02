"""Run a kaetzli module in the project's virtualenv: what every Python entry point calls.

    #!/usr/bin/env python3
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "python"))
    import launch
    launch.module("kaetzli.cve.scan")

The entry point runs on whatever python3 the host has (3.12 or newer), so this file is
stdlib only. It keeps python/.venv equal to requirements.txt and runs the module there:
when the lock or the interpreter changed since the venv was made, the venv is made again
from scratch (`python3 -m venv --clear`, then `pip install --require-hashes --no-deps`),
and a .pth file puts src/ on its path, so nothing is built or installed from this
project. Nothing is ever installed outside that venv. No uv: CLAUDE.md, Host-side code.

    python3 python/launch.py               # make or update the venv, nothing else
    python3 python/launch.py pytest -q     # any module, in the venv
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import subprocess
import sys
from pathlib import Path

MINIMUM = (3, 12)
PROJECT = Path(__file__).resolve().parent
VENV = PROJECT / ".venv"
LOCK = PROJECT / "requirements.txt"
SRC = PROJECT / "src"
STAMP = ".kaetzli-lock"


def python(venv: Path = VENV) -> Path:
    return venv / "bin" / "python"


def argv(module: str, args: list[str], venv: Path = VENV) -> list[str]:
    return [str(python(venv)), "-m", module, *args]


def stamp(lock: bytes, version: str = sys.version, base: str = sys.base_prefix) -> str:
    """What the venv was made from: the lock, and the interpreter (a venv is tied to it)."""
    h = hashlib.sha256(lock)
    h.update(f"\0{version}\0{base}".encode())
    return h.hexdigest()


def _run(cmd: list) -> None:
    # Onto stderr: an entry point's stdout is its report.
    subprocess.run([str(c) for c in cmd], check=True, stdout=sys.stderr)


def sync(venv: Path = VENV, lock: Path = LOCK, src: Path = SRC, run=_run) -> None:
    marker = venv / STAMP
    with lock.open("rb") as f:
        want = stamp(f.read())
        if marker.is_file() and marker.read_text() == want:
            return
        fcntl.flock(f, fcntl.LOCK_EX)  # two entry points starting at once make it once
        if marker.is_file() and marker.read_text() == want:
            return
        try:
            run([sys.executable, "-m", "venv", "--clear", venv])
            run([
                python(venv), "-m", "pip", "install", "--quiet",
                "--disable-pip-version-check", "--no-input",
                "--require-hashes", "--no-deps", "-r", lock,
            ])  # fmt: skip
        except subprocess.CalledProcessError:
            print(
                f"error: could not make {venv} from {lock.name} (python/README.md).\n"
                "       On Debian and Ubuntu, venv needs the python3-venv package.",
                file=sys.stderr,
            )
            sys.exit(2)
        v = sys.version_info
        site = venv / "lib" / f"python{v[0]}.{v[1]}" / "site-packages"
        site.mkdir(parents=True, exist_ok=True)
        (site / "kaetzli.pth").write_text(f"{src}\n")
        marker.write_text(want)


def ready(version=sys.version_info, sync=sync) -> None:
    """A Python new enough, and the venv up to date."""
    if tuple(version[:2]) < MINIMUM:
        print(
            f"error: the Python tools need Python {MINIMUM[0]}.{MINIMUM[1]} or newer; "
            f"this is {version[0]}.{version[1]} (python/README.md)",
            file=sys.stderr,
        )
        sys.exit(2)
    sync()


def module(name: str, args: list[str] | None = None, execv=os.execv, sync=sync,
           version=sys.version_info):  # fmt: skip
    ready(version, sync)
    a = argv(name, sys.argv[1:] if args is None else args)
    execv(a[0], a)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        module(sys.argv[1], sys.argv[2:])
    else:
        ready()
