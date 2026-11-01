"""python/launch.py: what every entry point in test/ and tools/ calls, on the host's python3."""

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import launch


def test_runs_the_module_in_the_locked_venv():
    assert launch.argv("kaetzli.cve.scan", ["output"]) == [
        "uv", "run", "--quiet", "--locked", "--project", str(launch.PROJECT),
        "python", "-m", "kaetzli.cve.scan", "output",
    ]  # fmt: skip
    assert Path(__file__).resolve().parents[1] == launch.PROJECT


def test_execs_uv_with_the_scripts_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "argv", ["test/cve-scan.py", "a", "b"])
    launch.module("m", execvp=lambda f, a: calls.append((f, a)), which=lambda _: "/usr/bin/uv")
    assert calls == [("uv", launch.argv("m", ["a", "b"]))]


def test_without_uv_says_where_to_get_it(capsys):
    with pytest.raises(SystemExit) as e:
        launch.module("m", args=[], execvp=None, which=lambda _: None)
    assert e.value.code == 2
    assert "uv is needed" in capsys.readouterr().err


def test_is_stdlib_only():
    """It runs before any venv exists, on whatever python3 the host has."""
    tree = ast.parse((launch.PROJECT / "launch.py").read_text())
    imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imports |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imports <= {"__future__", "os", "shutil", "sys", "pathlib"}
