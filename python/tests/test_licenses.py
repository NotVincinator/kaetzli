"""test/check-licenses.py: every package declares a DFSG-free license.

fixtures/licenses/<case>/declared.tsv is each package's LICENSE (empty: none declared),
checked against fixtures/licenses/dfsg-licenses.txt; expected/ is what the bash
test/check-licenses.sh printed and returned for that tree. Deliberate differences, none
of which the golden cases reach: an expression is parsed by license-expression, so one
that is not SPDX (an operator with nothing beside it, two identifiers with none between
them, unbalanced parentheses, a lower-case operator, an exception outside WITH or a
license inside it) is NOT VALID, where the bash version split on whitespace and passed
most of them; an identifier that is not allowed is named once, not once per use; and
packages are in byte order (glib before glibc), where the bash glob followed the host's
locale (C.UTF-8 in CI, which is byte order too).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from kaetzli import licenses, repo

FIXTURES = Path(__file__).parent / "fixtures" / "licenses"
CASES = sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())
ALLOWED = licenses.allowlist(FIXTURES / "dfsg-licenses.txt")


def declared(case: str) -> dict[str, str]:
    lines = (FIXTURES / case / "declared.tsv").read_text().splitlines()
    return dict(line.split("\t", 1) for line in lines)


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A checkout's worth of allowlist, at the path the messages name."""
    (tmp_path / "test").mkdir()
    shutil.copy(FIXTURES / "dfsg-licenses.txt", tmp_path / "test" / "dfsg-licenses.txt")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize("case", CASES)
def test_the_output_is_the_bash_versions(case, tree, capsys):
    expected = FIXTURES / case / "expected"
    rc = licenses.check(declared(case))
    out, err = capsys.readouterr()
    assert (out, err, rc) == (
        (expected / "stdout.txt").read_text(),
        (expected / "stderr.txt").read_text(),
        int((expected / "rc").read_text()),
    )


class TestAllowlist:
    def test_identifiers_without_comments_or_whitespace(self):
        assert ALLOWED == [
            "MIT",
            "BSD-3-Clause",
            "GPL-2.0-only",
            "GPL-2.0-or-later",
            "LGPL-2.1-or-later",
            "ISC",
            "Linux-syscall-note",
            "LicenseRef-PublicDomain",
        ]

    def test_an_empty_one_is_an_error(self, tree, capsys):
        (tree / "test" / "dfsg-licenses.txt").write_text("# nothing\n\n")
        assert licenses.check({"alpha": "MIT"}) == 1
        assert "error: test/dfsg-licenses.txt lists no licenses" in capsys.readouterr().err

    def test_the_real_one_is_read(self):
        real = licenses.allowlist(repo.ROOT / "test" / "dfsg-licenses.txt")
        assert {"MIT", "GCC-exception-3.1", "LicenseRef-IANA"} <= set(real)


class TestJudge:
    @pytest.mark.parametrize(
        "expression",
        [
            "MIT",
            "GPL-2.0-only WITH Linux-syscall-note",
            "LGPL-2.1-or-later AND (GPL-2.0-or-later OR BSD-3-Clause)",
            "GPL-2.0-only WITH Linux-syscall-note AND MIT",
            "MIT  AND\tISC",
            "LicenseRef-PublicDomain",
        ],
    )
    def test_allowed(self, expression):
        assert licenses.judge(expression, ALLOWED) == licenses.Verdict()

    def test_not_allowed_names_each_identifier_once_in_order(self):
        v = licenses.judge("Apache-2.0 AND (MIT OR Apache-2.0) AND SSPL-1.0", ALLOWED)
        assert v == licenses.Verdict(not_allowed=["Apache-2.0", "SSPL-1.0"])

    def test_identifiers_are_case_sensitive(self):
        assert licenses.judge("mit", ALLOWED).not_allowed == ["mit"]

    def test_an_exception_unknown_to_the_list_is_not_allowed(self):
        v = licenses.judge("GPL-2.0-only WITH Classpath-exception-2.0", ALLOWED)
        assert v.not_allowed == ["Classpath-exception-2.0"]

    @pytest.mark.parametrize(
        ("expression", "why"),
        [
            ("MIT AND", "AND requires two or more licenses"),
            ("MIT OR AND ISC", "Invalid operator sequence"),
            ("(MIT OR ISC", "Invalid expression"),
            ("MIT)", "Unbalanced parenthesis"),
            ("()", "not an SPDX expression"),
            ("MIT WITH", "Invalid expression"),
            ("MIT/ISC", "Invalid license key"),
            ("MIT ISC", "no operator between MIT and ISC"),
            ("MIT and ISC", "operators are upper case: and"),
            ("Linux-syscall-note", "Linux-syscall-note is an exception, only valid after WITH"),
            ("MIT AND Linux-syscall-note", "Linux-syscall-note is an exception"),
            ("GPL-2.0-only WITH MIT", "MIT is a license, not an exception"),
            ("GPL-2.0-only WITH LicenseRef-PublicDomain", "is a license, not an exception"),
            ("Linux-syscall-note WITH Linux-syscall-note", "is an exception, only valid after"),
        ],
    )
    def test_not_valid(self, expression, why):
        v = licenses.judge(expression, ALLOWED)
        assert v.not_allowed == []
        assert v.invalid is not None
        assert why in v.invalid

    def test_not_allowed_is_reported_before_a_role(self):
        # An unknown identifier cannot be judged as license or exception: name it.
        v = licenses.judge("GPL-2.0-only WITH Apache-2.0", ALLOWED)
        assert v == licenses.Verdict(not_allowed=["Apache-2.0"])


class TestNotValid:
    def test_reported_with_its_own_error(self, tree, capsys):
        rc = licenses.check({"alpha": "MIT ISC", "beta": "MIT", "gamma": "GPL-2.0-only WITH MIT"})
        out, err = capsys.readouterr()
        assert rc == 1
        assert out.splitlines()[0].startswith(f"  alpha        {'MIT ISC':<52} NOT VALID: ")
        assert out.splitlines()[1] == "  beta         MIT"
        assert "error: 2 package(s) declare a LICENSE that is not an SPDX expression:" in err
        assert "       alpha gamma\n" in err
        assert "not in test/dfsg-licenses.txt" not in err


def test_the_real_repository_passes():
    r = subprocess.run(
        [str(repo.ROOT / "test" / "check-licenses.py")], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stdout + r.stderr
    n = len(repo.all_packages())
    assert r.stdout.endswith(" packages, nothing undeclared or non-free\n")
    assert f", {n} packages," in r.stdout.splitlines()[-1]


def test_the_entry_point_runs_from_anywhere(tmp_path):
    r = subprocess.run(
        [str(repo.ROOT / "test" / "check-licenses.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
