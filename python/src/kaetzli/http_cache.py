"""Files fetched over HTTP and kept for a while, so a report asks each source once a day.

A 404 is cached as `{}` so it is not asked again; any other failure keeps the old copy
if there is one. Offline, any copy is fresh and nothing is fetched.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Response:
    status: int
    body: bytes


def urllib_fetch(url: str, timeout: float) -> Response:
    """GET with redirects followed and two retries on a connection error or a 5xx."""
    last: Exception | None = None
    for attempt in range(3):
        if attempt:
            time.sleep(2)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kaetzli-reports"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return Response(r.status, r.read())
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return Response(e.code, b"")
            last = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
    if isinstance(last, urllib.error.HTTPError):
        return Response(last.code, b"")
    raise OSError(str(last))


class Cache:
    def __init__(
        self,
        fetch: Callable[[str, float], Response] = urllib_fetch,
        max_age_minutes: int = 1440,
        offline: bool = False,
        timeout: float = 120,
    ):
        self.fetch = fetch
        self.max_age = max_age_minutes * 60
        self.offline = offline
        self.timeout = timeout

    def fresh(self, path: Path) -> bool:
        try:
            st = path.stat()
        except FileNotFoundError:
            return False
        if st.st_size == 0:
            return False
        return self.offline or time.time() - st.st_mtime <= self.max_age

    def get(self, path: Path, url: str) -> bool:
        """The file is there afterwards: fetched unless fresh, or an older copy."""
        if self.fresh(path):
            return True
        if self.offline:
            return False
        tmp = path.with_name(path.name + ".tmp")
        try:
            r = self.fetch(url, self.timeout)
        except OSError:
            r = Response(0, b"")
        if r.status == 200:
            tmp.write_bytes(r.body)
            tmp.replace(path)
            return True
        if r.status == 404:
            path.write_text("{}\n")
            return True
        tmp.unlink(missing_ok=True)
        return path.exists() and path.stat().st_size > 0
