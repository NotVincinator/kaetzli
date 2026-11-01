"""The checkout: where it is, its packages, and what tools/lib.sh and env.sh say.

env.sh is bash and stays bash (CLAUDE.md, Host-side code), so every value in it is read
by bash, through tools/lib.sh's own load_env, never parsed here.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class UnsupportedArch(ValueError):
    pass


def enter_root() -> Path:
    """cd to the repository root, as every script here does: paths are relative to it."""
    os.chdir(ROOT)
    return ROOT


def normalize_arch(arch: str | None = None) -> str:
    """amd64 or arm64, from either spelling; the host's when empty (tools/lib.sh)."""
    given = arch or os.uname().machine
    if given in ("x86_64", "amd64"):
        return "amd64"
    if given in ("aarch64", "arm64"):
        return "arm64"
    raise UnsupportedArch(f"unsupported architecture: {given} (expected amd64 or arm64)")


def all_packages() -> list[str]:
    """Every package name, in directory order."""
    return sorted(p.parent.name for p in (ROOT / "packages").glob("*/env.sh"))


def _bash(script: str, *args: str) -> str:
    return subprocess.run(
        ["bash", "-c", f"source tools/lib.sh\n{script}", "bash", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def lib_var(name: str) -> str:
    """A constant tools/lib.sh defines."""
    return _bash('printf %s "${!1}"', name)


def env_get(pkg: str, *names: str) -> list[str]:
    """Each variable from the package's env.sh, empty when unset (lib.sh's env_get)."""
    out = _bash('pkg=$1; shift; env_get "$pkg" "$@"', pkg, *names)
    values = out.split("\n")[: len(names)]
    return values + [""] * (len(names) - len(values))


def env_get_all(name: str) -> dict[str, str]:
    """One variable from every package's env.sh, in one bash process."""
    out = _bash(
        'for p in $(all_packages); do printf "%s\\t%s\\n" "$p" "$(env_get "$p" "$1")"; done',
        name,
    )
    return dict(line.split("\t", 1) for line in out.splitlines())


SOURCE_DATE_EPOCH = int(lib_var("KAETZLI_SOURCE_DATE_EPOCH"))
