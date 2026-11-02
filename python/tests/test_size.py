"""The size reports: test/rootfs-size.py, vs-debian-slim.py, size-history.py, oci-trim.py.

fixtures/size/ is real data from CI (run 41297815901 and the five green runs on main
before it), cut down or edited where a case needed one, and fixtures/size/expected/ is
what the bash versions printed for it. The deliberate differences are said where they
are tested: oci-trim's subtree count, and the usage line naming the .py.
"""

import io
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kaetzli import repo, report
from kaetzli.gh import Gh
from kaetzli.size import budget, history, sizes, slim, trim

FIXTURES = Path(__file__).parent / "fixtures" / "size"
EXPECTED = FIXTURES / "expected"
REL = FIXTURES.relative_to(repo.ROOT)  # what the bash versions were given, from the root


def expected(name: str) -> str:
    p = EXPECTED / name
    return p.read_text() if p.exists() else ""


class TestSizes:
    @pytest.mark.parametrize(
        ("n", "s"),
        [(0, "0.0"), (52428, "0.0"), (52429, "0.1"), (1048576, "1.0"), (77578159, "74.0")],
    )
    def test_mib_rounds_to_a_tenth_as_lib_sh_does(self, n, s):
        assert sizes.mib(n) == s

    @pytest.mark.parametrize(("d", "s"), [(0, "0.0"), (1, "+0.0"), (-3145728, "\u22123.0")])
    def test_delta_has_a_real_minus_sign(self, d, s):
        assert sizes.delta(d) == s

    def test_read(self):
        r = sizes.read(FIXTURES / "build" / "rootfs-size-erofs.txt")
        assert r.total == 77578159
        assert r.disk == 29212672
        assert r.archive == 0
        assert r.dirs[0] == (76670632, "usr")
        assert r.dir_sizes()["usr/lib"] == 46059063
        assert len(r.files) == 25
        assert r.files[0] == (6198832, "usr/lib/libcrypto.so.3")

    def test_a_missing_report_reads_as_empty(self, tmp_path):
        assert sizes.read_or_empty(tmp_path / "none.txt").total == 0


def run_main(module, argv, monkeypatch, tmp_path, env=None):
    """main(argv) as the entry point runs it: from the root, stdout, stderr and the job
    summary captured."""
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    rc = report.run(module.main, argv)
    s = summary.read_text() if summary.exists() else ""
    return rc, out.getvalue(), err.getvalue(), s


class TestBudget:
    @pytest.mark.parametrize("flavour", ["erofs", "oci"])
    @pytest.mark.parametrize("arch", ["amd64", "arm64"])
    def test_ci_reports_as_the_bash_version_printed_them(
        self, flavour, arch, monkeypatch, tmp_path
    ):
        given = (
            REL / "build" / f"rootfs-size-{flavour}.txt"
            if arch == "amd64"
            else REL / "budget" / f"{arch}-{flavour}.txt"
        )
        rc, out, err, s = run_main(
            budget, [flavour, str(given)], monkeypatch, tmp_path, {"ARCH": arch}
        )
        assert (rc, err) == (0, "")
        assert out == expected(f"budget-{flavour}-{arch}.out")
        assert s == expected(f"budget-{flavour}-{arch}.summary")

    @pytest.mark.parametrize(
        ("case", "argv", "rc"),
        [
            ("over", ["erofs", f"{REL}/budget/over.txt"], 1),
            ("small", ["erofs", f"{REL}/budget/small.txt"], 0),
            ("nototal", ["erofs", f"{REL}/budget/no-total.txt"], 1),
            ("missing", ["erofs", f"{REL}/budget/nonexistent.txt"], 1),
            ("usage", ["ext4"], 2),  # the usage line names rootfs-size.py now
        ],
    )
    def test_the_other_endings(self, case, argv, rc, monkeypatch, tmp_path):
        got = run_main(budget, argv, monkeypatch, tmp_path, {"ARCH": "amd64"})
        assert got == (
            rc,
            expected(f"budget-{case}.out"),
            expected(f"budget-{case}.err"),
            expected(f"budget-{case}.summary"),
        )

    def test_an_image_with_no_budget_line_is_an_error(self, monkeypatch, tmp_path):
        lines = (repo.ROOT / budget.BUDGET).read_text().splitlines(keepends=True)
        b = tmp_path / "budget.txt"
        b.write_text("".join(x for x in lines if not re.match(r"oci\s+arm64", x)))
        monkeypatch.setattr(budget, "BUDGET", str(b))
        rc, out, err, s = run_main(
            budget, ["oci", f"{REL}/budget/arm64-oci.txt"], monkeypatch, tmp_path,
            {"ARCH": "arm64"},
        )  # fmt: skip
        assert (rc, out, s) == (1, "", "")
        assert err == expected("budget-noline.err").replace("test/size-budget.txt", str(b))

    def test_budget_lines(self):
        assert budget.ceiling("erofs", "amd64", "# x\nerofs amd64 90\noci amd64 51\n") == 90
        assert budget.ceiling("oci", "arm64", "erofs amd64 90\n") is None


class TestSlim:
    @pytest.mark.parametrize(
        ("case", "ours", "theirs", "rc"),
        [
            ("smaller", "kaetzli-oci-amd64.txt", "debian-trixie-slim-amd64.txt", 0),
            ("larger", "debian-trixie-slim-amd64.txt", "kaetzli-oci-amd64.txt", 1),
        ],
    )
    def test_the_comparison_is_the_bash_versions(
        self, case, ours, theirs, rc, monkeypatch, tmp_path
    ):
        measured = []

        def measure(baseline, arch, dest):
            measured.append((baseline, arch, dest))
            shutil.copy(FIXTURES / "slim" / theirs, dest)

        monkeypatch.setattr(slim, "measure", measure)
        monkeypatch.setattr(slim, "THEIRS", str(tmp_path / "theirs.txt"))
        got = run_main(slim, [f"{REL}/slim/{ours}"], monkeypatch, tmp_path, {"ARCH": "amd64"})
        assert got == (
            rc,
            expected(f"slim-{case}.out"),
            expected(f"slim-{case}.err"),
            expected(f"slim-{case}.summary"),
        )
        assert measured == [("debian:trixie-slim", "amd64", Path(tmp_path / "theirs.txt"))]

    def test_the_baseline_report_is_build_rootfs_shaped(self, tmp_path):
        """What measure() writes from a tree, by du and find as build-rootfs.sh does."""
        root = tmp_path / "root"
        (root / "usr" / "lib").mkdir(parents=True)
        (root / "usr" / "lib" / "big").write_bytes(b"x" * 70000)
        (root / "usr" / "top").write_bytes(b"x" * 100)
        (root / "etc").mkdir()
        (root / "etc" / "small").write_bytes(b"x" * 10)
        lines = slim.tree_report(root, "debian:x", "amd64").splitlines()
        assert lines[0] == "# debian:x (amd64) filesystem, sizes in bytes. Written by " \
            "test/vs-debian-slim.py."  # fmt: skip
        assert lines[1].startswith("total ")
        assert [x.split(" ")[2] for x in lines if x.startswith("dir ")] == ["usr", "usr/lib"]
        assert [x for x in lines if x.startswith("file ")] == [
            "file 70000 usr/lib/big", "file 100 usr/top", "file 10 etc/small",
        ]  # fmt: skip


def fixture_gh(runs_json: Path):
    """gh answering from fixtures/size: runs.json for the list, runs/<id>/ for downloads."""
    from test_gh import FakeGh

    downloads = {}
    for d in (FIXTURES / "runs").iterdir():
        downloads[(d.name, "rootfs-size-amd64")] = {p.name: p.read_text() for p in d.iterdir()}
    answers = [
        (["gh", "auth", "status"], (0, "")),
        (["gh", "run", "list"], (0, runs_json.read_text())),
    ]
    return FakeGh(answers, downloads)


class TestHistory:
    @pytest.fixture
    def build(self, tmp_path):
        d = tmp_path / "output"
        shutil.copytree(FIXTURES / "build", d)
        return d

    def go(self, build, runs=12, gh=None):
        out = io.StringIO()
        history.history(
            gh or Gh(run=fixture_gh(FIXTURES / "runs.json")),
            "amd64", runs, build, report.Report(stdout=out),
            here="225ca1022573ae0a5a2dee815d49648fb2de059e", skip_run="41297815901",
        )  # fmt: skip
        return out.getvalue()

    def test_the_report_is_the_bash_versions(self, build):
        assert self.go(build) == expected("history.out")

    def test_runs_limits_how_far_back(self, build):
        assert self.go(build, runs=3) == expected("history-3.out")

    def test_runs_asks_for_twice_as_many(self, build):
        fake = fixture_gh(FIXTURES / "runs.json")
        self.go(build, runs=3, gh=Gh(run=fake))
        listing = next(c for c in fake.calls if c[:3] == ["gh", "run", "list"])
        assert listing[listing.index("--limit") + 1] == "6"

    def test_without_gh_this_build_alone(self, build):
        out = io.StringIO()
        with pytest.raises(report.Note) as n:
            history.history(
                Gh(which=lambda _: None), "amd64", 12, build, report.Report(stdout=out),
                here="225ca1022573ae0a5a2dee815d49648fb2de059e",
            )  # fmt: skip
        n.value.report.out(str(n.value))
        assert out.getvalue() == expected("history-nogh.out")

    def test_no_artifacts_is_a_note(self, build, tmp_path):
        empty = tmp_path / "runs.json"
        empty.write_text("[]")
        with pytest.raises(report.Note, match="no size artifacts found on `main`"):
            self.go(build, gh=Gh(run=fixture_gh(empty)))

    def test_no_reports_in_output_says_so_and_exits_0(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(history, "OUTPUT", str(tmp_path))
        assert report.run(history.main, ["amd64"]) == 0
        assert "no size reports in" in capsys.readouterr().err

    def test_an_ext4_report_continues_the_erofs_series(self, tmp_path):
        d = tmp_path / "1"
        d.mkdir()
        (d / "rootfs-size-ext4.txt").write_text("total 5\n")
        history.rename_ext4(d)
        assert (d / "rootfs-size-erofs.txt").read_text() == "total 5\n"


class TestTrim:
    def go(self, out_dir, full=False):
        buf = io.StringIO()
        rc = trim.trim(Path(out_dir), buf, full=full)
        text = re.sub(
            r"dependencies in .*/ are satisfied", "dependencies in <tree>/ are satisfied",
            buf.getvalue(),
        )  # fmt: skip
        return rc, text

    def test_the_report_is_the_bash_versions(self):
        """Except the subtree count: in C order systemd-boot sorts between systemd and
        systemd/…, and the bash version's awk then counted systemd's contents as tops
        of their own (10, not 8)."""
        assert self.go(FIXTURES / "trim") == (0, expected("trim-small.out"))

    def test_full_lists_every_removed_path(self):
        assert self.go(FIXTURES / "trim", full=True) == (0, expected("trim-small-full.out"))

    def test_tops(self):
        paths = ["a", "a-b", "a-b/c", "a/b", "a/b/c", "d/e"]
        assert trim.tops(paths) == ["a", "a-b", "d/e"]

    def test_areas(self):
        got = trim.areas(["a/b/c/d", "a/b/c/e", "a/b", "x"])
        assert got == [(2, "a/b/c"), (1, "a/b"), (1, "x")]

    def test_shared_libraries(self):
        names = ["usr/lib/libc.so.6", "usr/lib/libfoo.so", "usr/lib/libx.so.1.2.3",
                 "usr/lib/libx.so.1.a", "usr/lib/notlib.so", "lib/x"]  # fmt: skip
        assert trim.shared_libraries(names) == [
            "usr/lib/libc.so.6", "usr/lib/libfoo.so", "usr/lib/libx.so.1.2.3",
        ]  # fmt: skip

    def test_a_missing_input_is_an_error(self, tmp_path, capsys):
        assert trim.trim(tmp_path, io.StringIO()) == 1
        assert f"error: no {tmp_path}/rootfs-files-erofs.txt" in capsys.readouterr().err

    def test_a_failed_links_check_fails(self, tmp_path, monkeypatch, capsys):
        shutil.copytree(FIXTURES / "trim", tmp_path / "o")

        def deps(tree):
            return subprocess.CompletedProcess([], 1, "usr/bin/x: libgone.so.1\n", "")

        monkeypatch.setattr(trim, "check_deps", deps)
        buf = io.StringIO()
        assert trim.trim(tmp_path / "o", buf) == 1
        assert buf.getvalue().endswith("  usr/bin/x: libgone.so.1\n")
        assert "a binary in the container needs a library" in capsys.readouterr().err

    def test_the_layer_leaves_dev_out(self, tmp_path):
        tree = tmp_path / "tree"
        tree.mkdir()
        trim.unpack_layer(FIXTURES / "trim" / "kaetzli-oci.tar", tree)
        assert (tree / "etc" / "hostname").read_text() == "kaetzli\n"
        assert (tree / "bin").is_symlink()
        assert not (tree / "dev" / "console").exists()


@pytest.mark.parametrize(
    ("script", "args"),
    [
        ("rootfs-size.py", ["erofs", f"{REL}/build/rootfs-size-erofs.txt"]),
        ("oci-trim.py", [str(FIXTURES / "trim")]),
    ],
)
def test_the_entry_points(script, args, tmp_path):
    env = dict(os.environ, ARCH="amd64")
    env.pop("GITHUB_STEP_SUMMARY", None)
    p = subprocess.run(
        [sys.executable, repo.ROOT / "test" / script, *args],
        env=env, capture_output=True, text=True, cwd=tmp_path, check=False,
    )  # fmt: skip
    assert p.returncode == 0, p.stderr
    assert p.stdout
