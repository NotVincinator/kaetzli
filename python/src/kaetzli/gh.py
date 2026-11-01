"""CI's history through the gh CLI, which already holds the authentication.

The question every history report asks is the same: the last few green runs on main,
and which of them still have artifact X (artifacts expire, and a docs-only push succeeds
without building). It is answered here once.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

Runner = Callable[..., subprocess.CompletedProcess]


def _subprocess_run(argv: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, check=False, **kw)


@dataclass(frozen=True)
class Run:
    id: str
    sha: str
    date: str  # YYYY-MM-DD
    created: str = ""  # createdAt as gh gives it, 2026-11-01T10:30:53Z


class Gh:
    def __init__(
        self,
        repo: str | None = None,
        run: Runner = _subprocess_run,
        which: Callable[[str], str | None] = shutil.which,
    ):
        self.repo = repo
        self._run = run
        self._which = which

    def _repo_args(self) -> list[str]:
        return ["-R", self.repo] if self.repo else []

    def problem(self) -> str | None:
        """Why gh cannot be used, or None."""
        if not self._which("gh"):
            return "no `gh` on PATH"
        if os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
            return None
        if self._run(["gh", "auth", "status"]).returncode != 0:
            return "`gh` is not authenticated"
        return None

    def successful_runs(self, workflow: str, branch: str, limit: int) -> list[Run]:
        """Green runs of the workflow on the branch, newest first."""
        p = self._run(
            [
                "gh", "run", "list", *self._repo_args(),
                "--workflow", workflow, "--branch", branch, "--status", "success",
                "--limit", str(limit), "--json", "databaseId,headSha,createdAt",
            ]
        )  # fmt: skip
        if p.returncode != 0:
            return []
        try:
            runs = json.loads(p.stdout or "[]")
        except json.JSONDecodeError:
            return []
        return [
            Run(str(r["databaseId"]), r["headSha"], r["createdAt"][:10], r["createdAt"])
            for r in runs
        ]

    def live_artifacts(self, run_id: str, name: str) -> int:
        """How many unexpired artifacts called name the run has. Asked per run: the
        repository-wide listing is slow and fails with a 500."""
        repo = self.repo or "{owner}/{repo}"
        p = self._run(
            [
                "gh", "api", f"repos/{repo}/actions/runs/{run_id}/artifacts?name={name}",
                "-q", "[.artifacts[] | select(.expired | not)] | length",
            ]
        )  # fmt: skip
        if p.returncode != 0:
            return 0
        try:
            return int(p.stdout.strip() or 0)
        except ValueError:
            return 0

    def newest_run_with(
        self, artifact: str, workflow: str, branch: str, limit: int = 30
    ) -> str | None:
        for run in self.successful_runs(workflow, branch, limit):
            if self.live_artifacts(run.id, artifact) > 0:
                return run.id
        return None

    def download(self, run_id: str, name: str, dest: Path) -> bool:
        p = self._run(
            ["gh", "run", "download", run_id, *self._repo_args(), "-n", name, "-D", str(dest)]
        )
        return p.returncode == 0
