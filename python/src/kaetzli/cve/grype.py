"""grype: from PATH, or the pinned release, verified, into a cache of its own."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import urllib.request
from collections.abc import Callable
from pathlib import Path

from kaetzli import repo

VERSION = "0.120.1"
SHA256 = {
    "amd64": "0a9ee97ef5ae2ee953b0a80098105052e846cdbe319a57d808b519c33cd1343d",
    "arm64": "29f47391dc283aa79fcc38e65224cd61f64dec0ecfd0db7074128ebf8ff23514",
}


class GrypeUnavailable(RuntimeError):
    pass


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "kaetzli"


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=300) as r:
        return r.read()


def binary(
    pinned: bool,
    which: Callable[[str], str | None] = shutil.which,
    cache: Path | None = None,
    arch: str | None = None,
    fetch: Callable[[str], bytes] = _download,
    sha256: dict[str, str] = SHA256,
) -> Path:
    """grype on PATH, unless pinned (CI: GRYPE_PINNED) or absent; then the pinned release."""
    if not pinned and (found := which("grype")):
        return Path(found)
    arch = repo.normalize_arch(arch)
    d = (cache or cache_dir()) / f"grype-{VERSION}"
    exe = d / "grype"
    if os.access(exe, os.X_OK):
        return exe
    d.mkdir(parents=True, exist_ok=True)
    url = (
        f"https://github.com/anchore/grype/releases/download/v{VERSION}/"
        f"grype_{VERSION}_linux_{arch}.tar.gz"
    )
    try:
        data = fetch(url)
    except OSError as e:
        raise GrypeUnavailable(f"could not download {url}: {e}") from e
    if hashlib.sha256(data).hexdigest() != sha256[arch]:
        raise GrypeUnavailable(f"checksum mismatch for {url}")
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        member = t.getmember("grype")
        src = t.extractfile(member)
        if src is None:
            raise GrypeUnavailable(f"no grype binary in {url}")
        tmp = d / "grype.tmp"
        tmp.write_bytes(src.read())
        tmp.chmod(0o755)
        tmp.replace(exe)
    return exe


def _run(argv: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, check=False, **kw)


class Grype:
    def __init__(self, exe: Path | str, run: Callable[..., subprocess.CompletedProcess] = _run):
        self.exe = str(exe)
        self._run = run

    def db_update(self) -> bool:
        return self._run([self.exe, "db", "update"]).returncode == 0

    def db_built(self) -> str:
        """The vulnerability database's build date, which is what moves a count when the
        image did not change."""
        p = self._run([self.exe, "db", "status", "-o", "json"])
        try:
            status = json.loads(p.stdout)
        except (json.JSONDecodeError, TypeError):
            return "unknown"
        built = status.get("built") or status.get("Built") or "unknown"
        return str(built)[:10]

    def scan(self, sbom: Path, vex: Path | None = None) -> str | None:
        """grype's JSON report on the SBOM, or None if grype failed."""
        argv = [self.exe, "-q", f"sbom:{sbom}"]
        if vex is not None:
            argv += ["--vex", str(vex)]
        argv += ["-o", "json"]
        p = self._run(argv)
        return p.stdout if p.returncode == 0 else None
