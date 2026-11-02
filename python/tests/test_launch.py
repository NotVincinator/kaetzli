"""python/launch.py: what every entry point in test/ and tools/ calls, on the host's python3."""

import ast
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import launch

REPO = launch.PROJECT.parent


class FakeRun:
    """Records the commands sync runs; fails the ones whose argv contains `fail`."""

    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def __call__(self, cmd):
        self.calls.append([str(c) for c in cmd])
        if self.fail and self.fail in cmd:
            raise subprocess.CalledProcessError(1, cmd)


@pytest.fixture
def project(tmp_path):
    lock = tmp_path / "requirements.txt"
    lock.write_text("pyelftools==0.33 --hash=sha256:00\n")
    return tmp_path / ".venv", lock, tmp_path / "src"


def test_runs_the_module_with_the_venvs_python():
    assert launch.argv("kaetzli.cve.scan", ["output"]) == [
        str(launch.PROJECT / ".venv" / "bin" / "python"), "-m", "kaetzli.cve.scan", "output",
    ]  # fmt: skip
    assert Path(__file__).resolve().parents[1] == launch.PROJECT
    assert launch.PROJECT / "requirements.txt" == launch.LOCK


def test_syncs_then_execs_with_the_scripts_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "argv", ["test/cve-scan.py", "a", "b"])
    launch.module(
        "m",
        execv=lambda f, a: calls.append(("exec", f, a)),
        sync=lambda: calls.append(("sync",)),
    )
    a = launch.argv("m", ["a", "b"])
    assert calls == [("sync",), ("exec", a[0], a)]


def test_refuses_a_python_older_than_the_baseline(capsys):
    with pytest.raises(SystemExit) as e:
        launch.module("m", args=[], execv=None, sync=None, version=(3, 11, 9))
    assert e.value.code == 2
    assert "Python 3.12 or newer" in capsys.readouterr().err


def test_a_fresh_venv_is_made_from_the_lock_with_hashes(project):
    venv, lock, src = project
    run = FakeRun()
    launch.sync(venv, lock, src, run=run)
    assert run.calls == [
        [sys.executable, "-m", "venv", "--clear", str(venv)],
        [
            str(venv / "bin" / "python"), "-m", "pip", "install", "--quiet",
            "--disable-pip-version-check", "--no-input",
            "--require-hashes", "--no-deps", "-r", str(lock),
        ],
    ]  # fmt: skip
    site = venv / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}" / "site-packages"
    assert (site / "kaetzli.pth").read_text() == f"{src}\n"


def test_an_unchanged_lock_does_nothing(project):
    venv, lock, src = project
    launch.sync(venv, lock, src, run=FakeRun())
    run = FakeRun()
    launch.sync(venv, lock, src, run=run)
    assert run.calls == []


def test_a_changed_lock_rebuilds_the_venv_from_scratch(project):
    venv, lock, src = project
    launch.sync(venv, lock, src, run=FakeRun())
    lock.write_text("pyelftools==0.34 --hash=sha256:11\n")
    run = FakeRun()
    launch.sync(venv, lock, src, run=run)
    assert run.calls[0] == [sys.executable, "-m", "venv", "--clear", str(venv)]


def test_the_stamp_names_the_lock_and_the_interpreter():
    s = launch.stamp(b"a", version="3.12.3", base="/usr")
    assert s != launch.stamp(b"b", version="3.12.3", base="/usr")
    assert s != launch.stamp(b"a", version="3.13.0", base="/usr")
    assert s != launch.stamp(b"a", version="3.12.3", base="/opt/python")


def test_a_failed_install_is_tried_again_next_time(project, capsys):
    venv, lock, src = project
    with pytest.raises(SystemExit) as e:
        launch.sync(venv, lock, src, run=FakeRun(fail="pip"))
    assert e.value.code == 2
    assert "python3-venv" in capsys.readouterr().err
    run = FakeRun()
    launch.sync(venv, lock, src, run=run)
    assert len(run.calls) == 2


def test_is_stdlib_only():
    """It runs before any venv exists, on whatever python3 the host has."""
    tree = ast.parse((launch.PROJECT / "launch.py").read_text())
    imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imports |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imports <= {"__future__", "fcntl", "hashlib", "os", "subprocess", "sys", "pathlib"}


def test_the_baseline_is_the_same_everywhere():
    """Python 3.12: launch.py, pyproject.toml, ruff, and the Python Dependabot locks with."""
    assert launch.MINIMUM == (3, 12)
    pyproject = tomllib.loads((launch.PROJECT / "pyproject.toml").read_text())
    assert pyproject["project"]["requires-python"] == ">=3.12"
    assert pyproject["tool"]["ruff"]["target-version"] == "py312"
    assert (launch.PROJECT / ".python-version").read_text().strip() == "3.12"


def test_uv_is_not_a_dependency():
    """CLAUDE.md, Host-side code: uv is a no-go dependency. Nothing may run or require it."""
    uses = re.compile(r"\buv (run|lock|sync|pip|venv)\b|setup-uv|uv_build|uv\.lock|which\(\"uv\"\)")
    here = Path(__file__).resolve()
    dirs = (".github", "python", "test", "tools", "image")
    paths = [p for d in dirs for p in (REPO / d).rglob("*")]
    found = [
        str(p.relative_to(REPO))
        for p in paths
        if p.is_file() and p != here and ".venv" not in p.parts and "__pycache__" not in p.parts
        and uses.search(p.read_text(errors="replace"))
    ]  # fmt: skip
    assert found == []
    assert not (launch.PROJECT / "uv.lock").exists()
