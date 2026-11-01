import json
import subprocess

from kaetzli import gh


class FakeGh:
    """Answers gh invocations from a table of (argv prefix) -> (exit code, stdout)."""

    def __init__(self, answers=None, downloads=None):
        self.answers = answers or []
        self.downloads = downloads or {}
        self.calls = []

    def __call__(self, argv, **_kw):
        self.calls.append(argv)
        if argv[:3] == ["gh", "run", "download"]:
            run, name = argv[3], argv[argv.index("-n") + 1]
            dest = argv[argv.index("-D") + 1]
            files = self.downloads.get((run, name))
            if files is None:
                return subprocess.CompletedProcess(argv, 1, "", "no artifact")
            for rel, content in files.items():
                p = __import__("pathlib").Path(dest) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
            return subprocess.CompletedProcess(argv, 0, "", "")
        for prefix, (code, out) in self.answers:
            if argv[: len(prefix)] == prefix:
                return subprocess.CompletedProcess(argv, code, out, "")
        return subprocess.CompletedProcess(argv, 1, "", "unexpected")


RUNS = [
    {"databaseId": 30, "headSha": "c" * 40, "createdAt": "2026-10-30T10:00:00Z"},
    {"databaseId": 20, "headSha": "b" * 40, "createdAt": "2026-10-20T10:00:00Z"},
    {"databaseId": 10, "headSha": "a" * 40, "createdAt": "2026-10-10T10:00:00Z"},
]


def test_successful_runs_newest_first():
    fake = FakeGh([(["gh", "run", "list"], (0, json.dumps(RUNS)))])
    runs = gh.Gh(run=fake).successful_runs(workflow="ci.yml", branch="main", limit=6)
    assert [r.id for r in runs] == ["30", "20", "10"]
    assert runs[0].sha == "c" * 40
    assert runs[0].date == "2026-10-30"
    assert runs[0].created == "2026-10-30T10:00:00Z"
    argv = fake.calls[0]
    assert argv[argv.index("--workflow") + 1] == "ci.yml"
    assert argv[argv.index("--branch") + 1] == "main"
    assert argv[argv.index("--status") + 1] == "success"
    assert argv[argv.index("--limit") + 1] == "6"
    assert "-R" not in argv


def test_a_repository_is_named_when_given():
    fake = FakeGh([(["gh", "run", "list"], (0, "[]"))])
    gh.Gh(run=fake, repo="o/r").successful_runs(workflow="ci.yml", branch="main", limit=1)
    argv = fake.calls[0]
    assert argv[argv.index("-R") + 1] == "o/r"


def test_a_failed_listing_is_no_runs():
    fake = FakeGh([(["gh", "run", "list"], (1, ""))])
    assert gh.Gh(run=fake).successful_runs(workflow="ci.yml", branch="main", limit=1) == []


def test_download(tmp_path):
    fake = FakeGh(downloads={("20", "sbom-amd64"): {"sbom-erofs.json": "{}"}})
    g = gh.Gh(run=fake)
    assert g.download("20", "sbom-amd64", tmp_path / "20")
    assert (tmp_path / "20" / "sbom-erofs.json").read_text() == "{}"
    assert not g.download("10", "sbom-amd64", tmp_path / "10")


def test_live_artifacts():
    fake = FakeGh(
        [(["gh", "api", "repos/o/r/actions/runs/20/artifacts?name=cve-amd64"], (0, "2\n"))]
    )
    assert gh.Gh(run=fake, repo="o/r").live_artifacts("20", "cve-amd64") == 2
    assert gh.Gh(run=FakeGh(), repo="o/r").live_artifacts("20", "cve-amd64") == 0


def test_newest_run_with_an_artifact():
    fake = FakeGh(
        [
            (["gh", "run", "list"], (0, json.dumps(RUNS))),
            (["gh", "api", "repos/o/r/actions/runs/30/artifacts?name=cve-amd64"], (0, "0\n")),
            (["gh", "api", "repos/o/r/actions/runs/20/artifacts?name=cve-amd64"], (0, "1\n")),
        ]
    )
    run = gh.Gh(run=fake, repo="o/r").newest_run_with("cve-amd64", workflow="ci.yml", branch="main")
    assert run == "20"


def test_newest_run_with_an_artifact_none():
    fake = FakeGh([(["gh", "run", "list"], (0, json.dumps(RUNS)))])
    assert (
        gh.Gh(run=fake, repo="o/r").newest_run_with("x", workflow="ci.yml", branch="main") is None
    )


def test_usable(monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    logged_in = FakeGh([(["gh", "auth", "status"], (0, ""))])
    logged_out = FakeGh([(["gh", "auth", "status"], (1, ""))])
    assert gh.Gh(run=logged_in, which=lambda _: "/usr/bin/gh").problem() is None
    assert "not authenticated" in gh.Gh(run=logged_out, which=lambda _: "/usr/bin/gh").problem()
    assert "no `gh`" in gh.Gh(run=logged_in, which=lambda _: None).problem()
    monkeypatch.setenv("GH_TOKEN", "t")
    assert gh.Gh(run=logged_out, which=lambda _: "/usr/bin/gh").problem() is None
