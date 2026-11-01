import hashlib
import io
import subprocess
import tarfile

import pytest

from kaetzli.cve import grype


def tarball(content=b"#!/bin/sh\necho grype\n"):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in (("README.md", b"readme"), ("grype", content)):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class TestBinary:
    def test_from_path_unless_pinned(self, tmp_path):
        found = grype.binary(pinned=False, which=lambda _: "/usr/bin/grype", cache=tmp_path)
        assert str(found) == "/usr/bin/grype"

    def test_pinned_is_downloaded_verified_and_kept(self, tmp_path):
        data = tarball()
        urls = []

        def fetch(url):
            urls.append(url)
            return data

        sums = {"amd64": hashlib.sha256(data).hexdigest()}
        path = grype.binary(
            pinned=True, which=lambda _: "/usr/bin/grype", cache=tmp_path,
            arch="amd64", fetch=fetch, sha256=sums,
        )  # fmt: skip
        assert path == tmp_path / f"grype-{grype.VERSION}" / "grype"
        assert path.read_bytes().startswith(b"#!/bin/sh")
        assert path.stat().st_mode & 0o100
        assert urls == [
            f"https://github.com/anchore/grype/releases/download/v{grype.VERSION}/"
            f"grype_{grype.VERSION}_linux_amd64.tar.gz"
        ]
        assert not (path.parent / "README.md").exists()
        # A second time is the cache.
        grype.binary(pinned=True, cache=tmp_path, arch="amd64", fetch=fetch, sha256=sums)
        assert len(urls) == 1

    def test_a_checksum_mismatch_installs_nothing(self, tmp_path):
        with pytest.raises(grype.GrypeUnavailable, match="checksum"):
            grype.binary(
                pinned=True, cache=tmp_path, arch="amd64",
                fetch=lambda _: tarball(), sha256={"amd64": "0" * 64},
            )  # fmt: skip
        assert list((tmp_path / f"grype-{grype.VERSION}").iterdir()) == []

    def test_absent_from_path_falls_back_to_the_pin(self, tmp_path):
        data = tarball()
        path = grype.binary(
            pinned=False, which=lambda _: None, cache=tmp_path, arch="arm64",
            fetch=lambda _: data, sha256={"arm64": hashlib.sha256(data).hexdigest()},
        )  # fmt: skip
        assert path.name == "grype"

    def test_every_arch_is_pinned(self):
        assert set(grype.SHA256) == {"amd64", "arm64"}


class FakeRun:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        for prefix, (code, out) in self.answers:
            if argv[1 : 1 + len(prefix)] == prefix:
                return subprocess.CompletedProcess(argv, code, out, "")
        return subprocess.CompletedProcess(argv, 1, "", "")


class TestGrype:
    def test_db_built_is_a_date(self):
        run = FakeRun([(["db", "status"], (0, '{"built": "2026-11-01T04:12:33Z"}'))])
        assert grype.Grype("/g", run=run).db_built() == "2026-11-01"

    @pytest.mark.parametrize(
        ("out", "date"), [('{"Built": "2025-01-02T00:00:00Z"}', "2025-01-02"), ("{}", "unknown"),
                          ("not json", "unknown")],
    )  # fmt: skip
    def test_db_built_older_spellings_and_none(self, out, date):
        assert grype.Grype("/g", run=FakeRun([(["db", "status"], (0, out))])).db_built() == date

    def test_scan_with_and_without_vex(self, tmp_path):
        run = FakeRun([(["-q"], (0, "{}"))])
        g = grype.Grype("/g", run=run)
        assert g.scan(tmp_path / "s.json") == "{}"
        assert g.scan(tmp_path / "s.json", vex=tmp_path / "v.json") == "{}"
        assert run.calls == [
            ["/g", "-q", f"sbom:{tmp_path}/s.json", "-o", "json"],
            ["/g", "-q", f"sbom:{tmp_path}/s.json", "--vex", f"{tmp_path}/v.json", "-o", "json"],
        ]

    def test_a_failed_scan_is_none(self, tmp_path):
        assert grype.Grype("/g", run=FakeRun([])).scan(tmp_path / "s.json") is None
