"""Print a best-effort release-notes URL for a package and version:

    tools/release-notes.py <package> <version>

GitHub releases are preferred where packages/<pkg>/env.sh declares UPSTREAM_GITHUB. The
kernel has no GitHub release stream, so its canonical kernel.org ChangeLog is used.
Missing notes are normal and intentionally produce a non-zero exit with no output.
"""

from __future__ import annotations

import json
import sys

from kaetzli import repo
from kaetzli.updates import upstream
from kaetzli.updates.http import FetchError, Http


def url(pkg: str, version: str, http: Http) -> str | None:
    if pkg == "kernel":
        major = version.split(".", 1)[0]
        return f"https://cdn.kernel.org/pub/linux/kernel/v{major}.x/ChangeLog-{version}"
    github, sed = repo.env_get(pkg, "UPSTREAM_GITHUB", "UPSTREAM_SED")
    if not github:
        return None
    try:
        releases = json.loads(
            http.github(f"https://api.github.com/repos/{github}/releases?per_page=100")
        )
    except FetchError:
        return None
    releases = [r for r in releases if not (r.get("draft") or r.get("prerelease"))]
    tags = [r["tag_name"].removeprefix("v") for r in releases]
    if sed:
        try:
            tags = upstream.sed(sed, tags)
        except upstream.UpstreamError:
            return None
        if len(tags) != len(releases):  # an expression that deletes or adds lines
            return None
    for tag, release in zip(tags, releases, strict=True):
        if tag == version:
            return release["html_url"]
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not argv[0] or not argv[1]:
        return 1
    repo.enter_root()
    if not (repo.ROOT / "packages" / argv[0] / "env.sh").is_file():
        return 1
    found = url(argv[0], argv[1], Http())
    if found:
        print(found)
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
