"""tools/header-skew.py: the builder's -dev headers against the libraries we ship.

fixtures/skew/<case>/ours.txt is "dev package version" per line ("-" for build only), as
the bash tools/header-skew.sh fed its container; sid.tsv is each -dev package's version
as the builder's dpkg-query reports it, a virtual package's provider already followed
(empty: not installed). expected.txt is what the bash version printed: real/ is the
builder and packages/ on 2026-11-02, edge/ and current/ synthetic versions through a
stub dpkg-query in the builder, compared by its real dpkg --compare-versions. No
difference was needed.
"""

import subprocess
from pathlib import Path

import pytest

from kaetzli import header_skew, repo

FIXTURES = Path(__file__).parent / "fixtures" / "skew"
CASES = sorted(p.name for p in FIXTURES.iterdir())


def load(case: str):
    ours = [
        tuple(line.split(" ")) for line in (FIXTURES / case / "ours.txt").read_text().splitlines()
    ]
    sid = {}
    for line in (FIXTURES / case / "sid.tsv").read_text().splitlines():
        dev, version = line.split("\t")
        sid[dev] = version or None
    return ours, sid


@pytest.mark.parametrize("case", CASES)
def test_the_output_is_the_bash_versions(case):
    ours, sid = load(case)
    expected = (FIXTURES / case / "expected.txt").read_text()
    assert "".join(f"{line}\n" for line in header_skew.report(ours, sid)) == expected


@pytest.mark.parametrize(
    ("full", "upstream"),
    [
        ("2.4.0-1", "2.4.0"),
        ("1:2.6.0-1", "2.6.0"),
        ("1:2.78-1+b1", "2.78"),
        ("0.19+ds-1", "0.19"),
        ("1.5.7+dfsg-4", "1.5.7"),
        ("1:1.3.dfsg+really1.3.2-4", "1.3.2"),
        ("6.6+20260608-2", "6.6+20260608"),
        ("1.2-3-4", "1.2-3"),
        ("1.0", "1.0"),
        (None, "?"),
    ],
)
def test_upstream(full, upstream):
    assert header_skew.upstream(full) == upstream


class TestDevSection:
    def test_the_real_deps_txt(self):
        devs = header_skew.dev_section((repo.ROOT / "builder" / "deps.txt").read_text())
        assert "libssl-dev" in devs and "libffi-dev" in devs
        assert all(d.endswith("-dev") for d in devs)

    def test_between_the_markers_and_first_word_only(self):
        text = (
            "gcc\n"
            "# Development headers, only for libraries\n"
            "libfoo-dev   # a note\n"
            "  indented-is-not-a-package\n"
            "# a comment\n"
            "libbar-dev\n"
            "# The one exception to that\n"
            "libbaz-dev\n"
        )
        assert header_skew.dev_section(text) == ["libfoo-dev", "libbar-dev"]

    def test_every_dev_in_the_real_section_is_in_the_table(self):
        devs = header_skew.dev_section((repo.ROOT / "builder" / "deps.txt").read_text())
        assert set(devs) <= set(header_skew.OURS) | header_skew.BUILD_ONLY
        assert set(header_skew.OURS.values()) <= set(repo.all_packages())


class TestEntries:
    def test_ours_and_build_only(self):
        e = header_skew.entries(["libssl-dev", "libffi-dev"], {"openssl": "3.5.9"})
        assert e == [("libssl-dev", "openssl", "3.5.9"), ("libffi-dev", "-", "-")]

    def test_a_dev_not_in_the_table_is_an_error(self):
        with pytest.raises(header_skew.Unknown, match="libnew-dev"):
            header_skew.entries(["libnew-dev"], {})


def test_sid_versions_asks_the_builder_once():
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "libfoo-dev\t1:1.0-1\nlibbar-dev\t\n", "")

    sid = header_skew.sid_versions(["libfoo-dev", "libbar-dev"], "builder:tag", run=run)
    assert sid == {"libfoo-dev": "1:1.0-1", "libbar-dev": None}
    (argv,) = calls
    assert argv[:2] == ["podman", "run"] and "--network=none" in argv and "builder:tag" in argv
    assert argv[-2:] == ["libfoo-dev", "libbar-dev"]


def test_main_with_an_unknown_dev(monkeypatch, capsys):
    monkeypatch.setattr(header_skew, "OURS", {})
    assert header_skew.main([]) == 1
    assert "is in builder/deps.txt's -dev section but not in" in capsys.readouterr().err
