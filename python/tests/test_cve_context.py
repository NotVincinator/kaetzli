"""test/cve-context.py: the rules one at a time, then the whole report against the bash
version's, offline, from fixtures/context/ (real findings and answers, cut down, plus a
KEV entry, an EPSS top-10% percentile, a 404 and an unparseable answer of our own)."""

import io
import shutil
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

import pytest

from kaetzli.cve import context
from kaetzli.http_cache import Cache, Response

FIXTURES = Path(__file__).parent / "fixtures" / "context"
EXPECTED = FIXTURES / "expected"


class TestDebianSource:
    @pytest.mark.parametrize(
        ("pkg", "version", "src"),
        [
            ("kernel", "7.3.1", "linux"),
            ("podman", "5.7.0", "libpod"),
            ("stdlib", "1.27.1", "golang-1.27"),
            ("golang.org/x/crypto", "v0.54.0", "golang-go.crypto"),
            ("golang.org/x/net", "v0.57.0", "golang-golang-x-net"),
            ("google.golang.org/grpc", "v1.82.1", "golang-google-grpc"),
            ("openssh", "10.6p1", "openssh"),
        ],
    )
    def test_our_name_to_debians(self, pkg, version, src):
        assert context.debian_source(pkg, version) == src


class TestUpstreamVersion:
    @pytest.mark.parametrize(
        ("version", "upstream"),
        [
            ("1:1.3.dfsg+really1.3.2-4", "1.3.2"),
            ("1:10.2p1-6", "10.2p1"),
            ("2.1.9+ds1-5", "2.1.9"),
            ("1.31.4+ds-1", "1.31.4"),
            ("5.2+dfsg.1-3", "5.2"),
            ("3.0~repack-1", "3.0"),
            ("7.2.11-1", "7.2.11"),
            ("2.43-7", "2.43"),
            ("1.0~rc1-2", "1.0~rc1"),
            ("0.0~git20250201.1a2b3c4-1", "0.0~git20250201.1a2b3c4"),
        ],
    )
    def test_debians(self, version, upstream):
        """Epoch and revision are Debian's; +really names the upstream version a
        package really is, and +dfsg/+ds/+repack are a repacked tarball of it."""
        assert context.upstream_version(version) == upstream

    @pytest.mark.parametrize(
        ("debian", "ours", "relation"),
        [
            ("1:1.3.dfsg+really1.3.2-4", "1.3.2", "same"),
            ("1:0.60.0-1", "v0.57.0", "newer"),
            ("6.0.12-1", "7.3.1", "older"),
            ("2.43-7", "2.44", "older"),
            ("1.10-1", "1.9", "newer"),
            ("1:10.2p1-6", "10.2p1", "same"),
            ("2.1.9+ds1-5", "2.1.9", "same"),
            # Where comparing the digits alone was wrong: letters and ~ carry meaning,
            # and dpkg's order is the one Debian's fixed_version is written in.
            ("2026a-1", "2026b", "older"),
            ("2026c-1", "2026b", "newer"),
            ("10.2p2-1", "10.2p1", "newer"),
            ("1.0~rc1-2", "1.0", "older"),
            ("1.0-1", "1.0~rc2", "newer"),
            # A hyphen in our version is ours, not a Debian revision.
            ("1.2.2-1", "v0.0.0-20250101-abc", "newer"),
            ("1.2.2-1", "1.2.3-20250101-abc", "older"),
        ],
    )
    def test_against_ours(self, debian, ours, relation):
        assert context.against(debian, ours) == relation

    def test_a_version_debian_cannot_read_relates_to_nothing(self):
        assert context.against("", "1.0") == ""
        assert context.against("1.0-1", "") == ""


class TestDebianVerdict:
    def test_none(self):
        assert context.debian_verdict(None) == ""

    @pytest.mark.parametrize(
        ("sid", "verdict"),
        [
            (None, "glibc: not in sid"),
            ({"status": "resolved", "fixed_version": "0"}, "glibc: not affected"),
            ({"status": "resolved", "fixed_version": "2.43-7"}, "glibc: fixed in 2.43-7"),
            ({"status": "open"}, "glibc: open"),
            ({"status": "open", "urgency": "unimportant"}, "glibc: open (unimportant)"),
            ({"status": "undetermined", "urgency": "low"}, "glibc: undetermined"),
        ],
    )
    def test_verdicts(self, sid, verdict):
        assert context.debian_verdict({"src": "glibc", "sid": sid}) == verdict


class TestDebianEntry:
    ENTRIES: ClassVar = [
        {"src": "linux-6.12", "sid": None},
        {"src": "golang-1.24", "sid": {"status": "open"}},
        {"src": "linux", "sid": {"status": "resolved", "fixed_version": "7.2.11-1"}},
    ]

    def test_our_source_first(self):
        assert context.debian_entry(self.ENTRIES, "linux")["src"] == "linux"

    def test_else_the_first_tracked_in_sid(self):
        assert context.debian_entry(self.ENTRIES, "tar")["src"] == "golang-1.24"

    def test_else_the_first(self):
        assert context.debian_entry(self.ENTRIES[:1], "tar")["src"] == "linux-6.12"

    def test_none_tracked(self):
        assert context.debian_entry([], "tar") is None


def finding(**kw):
    base = {"id": "CVE-1", "cve": "CVE-1", "pkg": "openssh", "version": "10.6p1"}
    return context.Finding(**{**base, **kw})


def sources(**kw):
    return context.Sources(**kw)


class TestHint:
    def test_exploited_comes_first_whatever_else(self):
        s = sources(
            kev={"CVE-1": {"added": "2026-10-01", "ransomware": "Unknown"}},
            debian={
                "CVE-1": [{"src": "openssh", "sid": {"status": "resolved", "fixed_version": "0"}}]
            },
        )
        assert context.row(finding(), s).hint == "1 exploited (KEV)"

    @pytest.mark.parametrize(
        ("fixed", "hint"),
        [
            ("1:10.6p1-3", "2 Debian patched this version"),
            ("1:10.7p1-1", "3 fixed in a newer release"),
            ("1:9.2p1-2", "5 fixed before our version (likely FP)"),
        ],
    )
    def test_by_where_debian_fixed_it(self, fixed, hint):
        s = sources(
            debian={
                "CVE-1": [{"src": "openssh", "sid": {"status": "resolved", "fixed_version": fixed}}]
            }
        )
        assert context.row(finding(), s).hint == hint

    def test_a_fix_in_another_debian_package(self):
        s = sources(
            debian={
                "CVE-1": [{"src": "other", "sid": {"status": "resolved", "fixed_version": "1-1"}}]
            }
        )
        assert context.row(finding(), s).hint == "4 Debian fixed the copy in another package"

    def test_not_affected_and_unimportant(self):
        na = sources(
            debian={
                "CVE-1": [{"src": "openssh", "sid": {"status": "resolved", "fixed_version": "0"}}]
            }
        )
        assert context.row(finding(), na).hint == "5 Debian: not affected"
        unimp = sources(
            debian={
                "CVE-1": [{"src": "openssh", "sid": {"status": "open", "urgency": "unimportant"}}]
            }
        )
        assert context.row(finding(), unimp).hint == "5 distro: unimportant"
        negligible = sources(ubuntu={"CVE-1": "negligible"})
        assert context.row(finding(), negligible).hint == "5 distro: unimportant"

    def test_open_and_untracked(self):
        assert context.row(finding(), sources()).hint == "4 not tracked by Debian"
        s = sources(debian={"CVE-1": [{"src": "openssh", "sid": {"status": "open"}}]})
        assert context.row(finding(), s).hint == "4 open in Debian too"

    def test_epss_top_ten_percent_is_said_unless_likely_a_false_positive(self):
        s = sources(epss={"CVE-1": context.Epss("0.5", "0.95")})
        assert context.row(finding(), s).hint == "4 not tracked by Debian, EPSS top 10%"
        s.debian = {
            "CVE-1": [{"src": "openssh", "sid": {"status": "resolved", "fixed_version": "0"}}]
        }
        assert context.row(finding(), s).hint == "5 Debian: not affected"


class TestFindings:
    def test_distinct_across_reports(self):
        fs = context.distinct_findings(context.grype_reports(FIXTURES / "build"))
        assert len(fs) == 17
        net = [f for f in fs if f.pkg == "golang.org/x/net"]
        assert {f.version for f in net} == {"v0.57.0", "v0.58.0"}
        zlib = next(f for f in fs if f.pkg == "zlib")
        assert zlib.docs == "erofs,oci"

    def test_the_cve_is_the_id_or_the_first_related_cve(self):
        fs = {f.id: f for f in context.distinct_findings(context.grype_reports(FIXTURES / "build"))}
        assert fs["GO-2026-6603"].cve == "CVE-2026-78659"
        assert fs["GHSA-zzzz-yyyy-xxxx"].cve == ""

    def test_cvss_is_the_best_score_as_written(self):
        fs = {f.id: f for f in context.distinct_findings(context.grype_reports(FIXTURES / "build"))}
        assert fs["CVE-2026-99999"].cvss == Decimal("5.0")
        assert fs["GHSA-zzzz-yyyy-xxxx"].cvss is None

    def test_vex_and_sbom_copies_are_not_reports(self):
        names = [p.name for p in context.grype_reports(FIXTURES / "build")]
        assert names == ["erofs.json", "ext-kubernetes.json", "ext-podman.json", "oci.json"]


class TestPercent:
    @pytest.mark.parametrize(
        ("value", "text"),
        [("0.004690000", "0.5%"), ("0.018330000", "1.8%"), ("0.0099", "1%"), ("1", "100%"),
         ("0.00004", "0%"), ("0.0005", "0.1%"), (None, "")],
    )  # fmt: skip
    def test_one_decimal_half_up(self, value, text):
        assert context.percent(value) == text


class TestEpssBatches:
    def test_cached_by_the_batch_as_the_bash_version_named_it(self):
        cves = ["CVE-2007-2768", "CVE-2008-3844"]
        assert context.epss_batch_key(cves) == context.epss_batch_key(list(cves))
        (key,) = [p.stem for p in (FIXTURES / "cache/kaetzli/cve-context/epss").glob("*.json")]
        all_cves = sorted({f.cve for f in context.distinct_findings(
            context.grype_reports(FIXTURES / "build")) if f.cve})  # fmt: skip
        assert context.epss_batch_key(all_cves) == key

    def test_a_hundred_at_a_time(self):
        cves = [f"CVE-2026-{i}" for i in range(250)]
        assert [len(b) for b in context.batches(cves, 100)] == [100, 100, 50]


@pytest.fixture
def cache_dir(tmp_path):
    d = tmp_path / "cache"
    shutil.copytree(FIXTURES / "cache" / "kaetzli" / "cve-context", d)
    for p in d.rglob("*.json"):
        p.touch()  # fetched just now: a checkout's mtimes say nothing about the cache
    return d


@pytest.fixture
def build(tmp_path):
    d = tmp_path / "build"
    shutil.copytree(FIXTURES / "build", d)
    return d


class TestTheReport:
    def run(self, build, cache_dir, cache):
        out, err = io.StringIO(), io.StringIO()
        context.report(build, cache_dir, cache, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue().replace(str(build), "<dir>")

    def test_is_the_bash_versions(self, build, cache_dir):
        out, err = self.run(build, cache_dir, Cache(offline=True))
        assert out == (EXPECTED / "stdout.md").read_text()
        assert err == (EXPECTED / "stderr.txt").read_text()
        assert (build / "cve-context.tsv").read_text() == (EXPECTED / "cve-context.tsv").read_text()

    def test_offline_asks_nobody(self, build, cache_dir):
        def fetch(url, timeout):
            raise AssertionError(f"fetched {url}")

        self.run(build, cache_dir, Cache(fetch=fetch, offline=True))

    def test_online_asks_what_is_not_cached(self, build, cache_dir):
        (cache_dir / "kev.json").unlink()
        for p in (cache_dir / "redhat").glob("*.json"):
            p.unlink()
        urls = []

        def fetch(url, timeout):
            urls.append(url)
            return Response(404, b"")

        self.run(build, cache_dir, Cache(fetch=fetch))
        assert (
            "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
            in urls
        )
        redhat = [u for u in urls if "access.redhat.com" in u]
        assert len(redhat) == 15
        # Fresh in the cache but for the one CVE Ubuntu had no answer for.
        assert [u for u in urls if "ubuntu.com" in u] == [
            "https://ubuntu.com/security/cves/CVE-2026-99999.json"
        ]
        assert not [u for u in urls if "security-tracker.debian.org" in u]

    def test_unreachable_sources_are_notes_and_empty_columns(self, build, tmp_path):
        out, err = self.run(build, tmp_path / "empty", Cache(offline=True))
        assert "_Debian security tracker unreachable_" in err
        assert "_CISA KEV unreachable_" in err
        assert "_EPSS unreachable or knows none of these_" in err
        assert (
            "| not tracked by Debian | CVE-2008-3844 | openssh 10.6p1 | High |  |  |  |  |" in out
        )

    def test_no_reports_is_a_note(self, tmp_path):
        out, err = self.run(tmp_path, tmp_path / "c", Cache(offline=True))
        assert out == ""
        assert "no grype reports" in err


class TestWhichScan:
    def test_this_checkouts_own_first(self, tmp_path, monkeypatch):
        (tmp_path / "output" / "cve").mkdir(parents=True)
        (tmp_path / "output" / "cve" / "erofs.json").write_text("{}")
        monkeypatch.chdir(tmp_path)
        assert context.which_scan(None, run=None, arch="amd64", gh=None) == Path("output")

    def test_else_cis_newest_downloaded_once(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        class FakeGh:
            downloads = 0

            def problem(self):
                return None

            def newest_run_with(self, artifact, workflow, branch):
                assert artifact == "cve-arm64"
                return "42"

            def download(self, run_id, name, dest):
                FakeGh.downloads += 1
                (dest / "cve").mkdir(parents=True)
                (dest / "cve" / "erofs.json").write_text("{}")
                return True

        d = context.which_scan(None, run=None, arch="arm64", gh=FakeGh())
        assert d == Path("output/cve-ci/42-arm64")
        assert (d / "cve" / "erofs.json").exists()
        context.which_scan(None, run=None, arch="arm64", gh=FakeGh())
        assert FakeGh.downloads == 1

    def test_a_run_must_be_a_number(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as e:
            context.which_scan(
                None, run="abc", arch="amd64", gh=type("G", (), {"problem": lambda s: None})()
            )
        assert e.value.code == 2
