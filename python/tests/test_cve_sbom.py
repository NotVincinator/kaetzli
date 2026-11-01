import json
from pathlib import Path
from typing import ClassVar

from kaetzli.cve import sbom

FIXTURES = Path(__file__).parent / "fixtures" / "scan"


def load():
    return json.loads((FIXTURES / "sbom.json").read_text())


class TestVex:
    def test_a_statement_per_cve_a_patch_fixes(self):
        doc = sbom.vex(load(), timestamp="2026-01-01T00:00:00Z")
        assert doc["@context"] == "https://openvex.dev/ns/v0.2.0"
        assert doc["timestamp"] == "2026-01-01T00:00:00Z"
        assert [s["vulnerability"]["name"] for s in doc["statements"]] == [
            "CVE-2026-18374",
            "CVE-2026-19499",
            "CVE-2026-7",
        ]
        first = doc["statements"][0]
        assert first["products"] == [{"@id": "pkg:generic/glibc@2.44"}]
        assert first["status"] == "fixed"

    def test_the_note_names_the_package_whose_patch_it_is(self):
        # The bash version said "packages//patches/...": its jq read .name from the
        # reference rather than the package.
        doc = sbom.vex(load(), timestamp="t")
        assert doc["statements"][0]["status_notes"] == (
            "fixed by packages/glibc/patches/upstream/0039-libio-Fix.patch"
        )

    def test_keys_in_openvex_order(self):
        doc = sbom.vex(load(), timestamp="t")
        assert list(doc) == ["@context", "@id", "author", "timestamp", "version", "statements"]
        assert list(doc["statements"][0]) == [
            "vulnerability",
            "products",
            "status",
            "status_notes",
        ]

    def test_none_without_fixes(self):
        doc = {"packages": [{"name": "x", "externalRefs": []}, {"name": "y"}]}
        assert sbom.vex(doc, timestamp="t") is None

    def test_timestamp_from_epoch(self):
        assert sbom.timestamp(1767225600) == "2026-01-01T00:00:00Z"


class TestEnrich:
    CPES: ClassVar = {
        "glibc": ["cpe:2.3:a:gnu:glibc:2.45:*:*:*:*:*:*:*"],
        "gawk": [
            "cpe:2.3:a:gnu:gawk:5.4.0:*:*:*:*:*:*:*",
            "cpe:2.3:a:gawk_project:gawk:5.4.0:*:*:*:*:*:*:*",
        ],
        "tcpdump": ["cpe:2.3:a:tcpdump:tcpdump:4.99.5:*:*:*:*:*:*:*"],
    }

    def test_todays_cpes_with_the_sboms_version(self):
        pkgs = {p["name"]: p for p in sbom.enrich(load(), self.CPES)["packages"]}
        added = [r for r in pkgs["gawk"]["externalRefs"] if r["referenceType"] == "cpe23Type"]
        assert [r["referenceLocator"] for r in added] == [
            "cpe:2.3:a:gnu:gawk:5.3.1:*:*:*:*:*:*:*",
            "cpe:2.3:a:gawk_project:gawk:5.3.1:*:*:*:*:*:*:*",
        ]
        assert added[0]["referenceCategory"] == "SECURITY"

    def test_a_package_that_has_a_cpe_keeps_it(self):
        before = load()["packages"][0]
        after = sbom.enrich(load(), self.CPES)["packages"][0]
        assert after == before

    def test_a_vendor_record_gets_none(self):
        pkgs = {p["name"]: p for p in sbom.enrich(load(), self.CPES)["packages"]}
        assert "externalRefs" not in pkgs["tcpdump-vendor"]

    def test_cpe_map_from_env(self):
        env = {"glibc": "cpe:a cpe:b ", "bash": "", "gawk": "  cpe:c"}
        assert sbom.cpe_map(env) == {"glibc": ["cpe:a", "cpe:b"], "gawk": ["cpe:c"]}


class TestJqStyleJson:
    def test_two_space_indent_and_raw_unicode(self):
        assert sbom.dumps({"a": [1, {"b": "ä"}], "e": [], "o": {}}) == (
            '{\n  "a": [\n    1,\n    {\n      "b": "ä"\n    }\n  ],\n  "e": [],\n  "o": {}\n}\n'
        )
