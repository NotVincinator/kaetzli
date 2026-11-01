"""image/sbom.py, the SBOM writer the assembly container runs on its own python3.

fixtures/sbom/expected/ is what the bash image/sbom.sh, with build-rootfs.sh's and
build-extension.sh's document around it, wrote for fixtures/sbom/tree: the same elements
with the same keys in the same order, which re-serialising it with sbom.py's own
serialiser shows to the byte. Only the layout differs, and JSON escaping is now complete.
"""

import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from kaetzli import repo

SCRIPT = repo.ROOT / "image" / "sbom.py"
FIXTURES = Path(__file__).parent / "fixtures" / "sbom"
TREE = FIXTURES / "tree"
CREATED = "2026-01-01T00:00:00Z"

spec = importlib.util.spec_from_file_location("sbom", SCRIPT)
sbom = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sbom)

CASES = {
    "image-extra": [
        "image", str(TREE), "--name", "kaetzli-erofs-amd64", "--created", CREATED,
        "--extra", str(FIXTURES / "extra-files.txt"),
        "--unresolved", str(FIXTURES / "unresolved.txt"),
    ],
    "image": [
        "image", str(TREE), "--name", "kaetzli-oci-amd64", "--created", CREATED,
        "--unresolved", "/dev/null",
    ],
    "extension": [
        "extension", str(TREE), "--name", "kaetzli-ext-podman-amd64", "--created", CREATED,
    ],
}  # fmt: skip


@pytest.mark.parametrize("case", CASES)
def test_the_document_is_the_bash_versions(case):
    """Run as the assembly runs it: the file, on a bare python3, with no venv."""
    r = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *CASES[case]],
        capture_output=True,
        text=True,
        check=True,
    )
    golden = json.loads((FIXTURES / "expected" / f"{case}.json").read_text())
    assert r.stdout == sbom.dumps(golden)


def test_stdlib_only():
    """The assembly image has python3 and nothing else: no kaetzli, no third party."""
    tree = ast.parse(SCRIPT.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}


def record(tmp_path, name, text, modules=None):
    d = tmp_path / "usr/share/kaetzli"
    (d / "components").mkdir(parents=True, exist_ok=True)
    (d / "components" / name).write_text(text)
    if modules is not None:
        (d / "modules").mkdir(exist_ok=True)
        (d / "modules" / name).write_text(modules)
    return tmp_path


def test_any_value_is_escaped(tmp_path):
    """jstr escaped backslash, quote, tab and CR; any other control character made the
    document unparseable."""
    odd = 'a\\b"c\td\re\x1bf\x01g ü'
    tree = record(tmp_path, "odd", f"name=odd\nversion={odd}\nlicense={odd}\nurl={odd}\n")
    doc = json.loads(sbom.dumps(sbom.document("image", "n", CREATED, tree)))
    pkg = doc["packages"][1]
    assert (pkg["versionInfo"], pkg["licenseDeclared"], pkg["downloadLocation"]) == (odd,) * 3


def test_spdx_ids_are_letters_digits_dots_and_dashes():
    # tr worked on bytes, so a two-byte character is two dashes.
    assert sbom.spdxid("lib+odd.so.2") == "lib-odd.so.2"
    assert sbom.spdxid("ü/x_y") == "---x-y"


def test_purls():
    assert sbom.purl_path("pkg:golang/github.com/a/b@v1") == "github.com/a/b@v1"
    assert sbom.purl_path("pkg:cargo/serde@1.0") == "serde@1.0"
    p = sbom.module_package("x", "pkg:generic/noversion")
    assert (p["name"], p["versionInfo"]) == ("noversion", "noversion")


def test_records_without_a_name_and_blank_lines_are_skipped(tmp_path):
    tree = record(tmp_path, "a", "name=a\nversion=1\nfix=\n", modules="\npkg:cargo/c@1\n\n")
    record(tmp_path, "b", "version=2\n")
    doc = sbom.document("extension", "n", CREATED, tree)
    assert [p["SPDXID"] for p in doc["packages"]] == [
        "SPDXRef-Extension",
        "SPDXRef-Package-a",
        "SPDXRef-Module-a-c-1",
    ]
    assert len(doc["packages"][1]["externalRefs"]) == 1


def test_a_value_may_contain_and_end_in_equals(tmp_path):
    # bash's `IFS== read` dropped one trailing '=' from a value.
    tree = record(tmp_path, "a", "name=a\nurl=https://x/?a=b=\n")
    assert sbom.document("image", "n", CREATED, tree)["packages"][1]["downloadLocation"] == (
        "https://x/?a=b="
    )
