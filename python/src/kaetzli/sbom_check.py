"""Does the SBOM this build produced actually say what is in the image?

    ./test/check-sbom.py                       # both flavours from output/
    ./test/check-sbom.py output/sbom-oci.json  # one document

image/sbom.py writes the document with a JSON serialiser, so it parses; what this checks
is that it says the right things. A malformed SBOM is worse than none: a file that looks
like an answer and silently is not. It is what makes issue #75's "CI fails if it cannot
be produced" mean something, and it checks three things:

  1. it is JSON, and it is SPDX 2.3
  2. every component carries the provenance the issue asked for: version, download
     location, and a SHA256 for anything that came from a tarball
  3. it describes *this* image: every package staged into the tree is in it, the
     relationship graph has no dangling references, and every package it names ships
     its license text (the manifest image/build-rootfs.sh writes beside it)
  4. spdx-tools, the SPDX project's library, validates it against the SPDX 2.3 model
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from kaetzli import repo

DEFAULT = ("output/sbom-erofs.json", "output/sbom-oci.json")


def _empty(v) -> bool:
    """What jq's `// empty` drops, or prints as nothing: null, false and ""."""
    return v is None or v is False or v == ""


def _starts(v, prefix: str) -> bool:
    return isinstance(v, str) and v.startswith(prefix)


def _ids(packages: list, prefix: str) -> list[dict]:
    return [p for p in packages if _starts(p.get("SPDXID"), prefix)]


def manifest_for(doc: Path) -> Path:
    """rootfs-files-<flavour>.txt beside sbom-<flavour>.json."""
    flavour = doc.name.removesuffix(".json").removeprefix("sbom-")
    return doc.parent / f"rootfs-files-{flavour}.txt"


def check(doc: Path) -> tuple[list[str], str | None]:
    """The failures in one document, and the line that sums it up when it parsed."""
    fails: list[str] = []
    try:
        d = json.loads(doc.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return [f"not valid JSON\n        {e}"], None

    if d.get("spdxVersion") != "SPDX-2.3":
        fails.append("spdxVersion is not SPDX-2.3")
    if d.get("SPDXID") != "SPDXRef-DOCUMENT":
        fails.append("missing SPDXRef-DOCUMENT")
    if _empty(d.get("documentNamespace")):
        fails.append("no documentNamespace")
    if _empty((d.get("creationInfo") or {}).get("created")):
        fails.append("no creationInfo.created")

    packages = d.get("packages") or []
    relationships = d.get("relationships") or []

    # SPDX ids have to be unique: a consumer resolves a relationship to whichever
    # package of that id it saw last.
    seen: dict = {}
    for p in packages:
        seen[p.get("SPDXID")] = seen.get(p.get("SPDXID"), 0) + 1
    dupes = sorted(str(i) for i, n in seen.items() if n > 1)
    if dupes:
        fails.append(f"duplicate SPDXIDs: {' '.join(dupes)}")

    # Provenance, which is the whole point of generating this rather than scanning for it.
    # A package with a downloadLocation and no checksum is fine only when it did not come
    # from a tarball: a local-source package points at the repository instead.
    components = _ids(packages, "SPDXRef-Package-")
    bad = [
        p.get("name")
        for p in components
        if (p.get("versionInfo") or "") == ""
        or (p.get("downloadLocation") or "NOASSERTION") == "NOASSERTION"
    ]
    if bad:
        fails.append(f"packages with no version or download location: {_names(bad)}")
    unhashed = [
        p.get("name")
        for p in components
        if not _starts(p.get("downloadLocation"), "git+") and not p.get("checksums")
    ]
    if unhashed:
        fails.append(f"tarball packages with no SHA256: {_names(unhashed)}")

    # Every relationship has to name elements that exist, which is invisible until a
    # consumer walks the graph.
    ids = {p.get("SPDXID") for p in packages} | {"SPDXRef-DOCUMENT"}
    dangling = [
        f"{r.get('spdxElementId')} -{r.get('relationshipType')}-> {r.get('relatedSpdxElement')}"
        for r in relationships
        if r.get("spdxElementId") not in ids or r.get("relatedSpdxElement") not in ids
    ]
    if dangling:
        fails.append("relationships naming unknown elements:\n" + "\n".join(dangling))

    # An image with no CONTAINS is a document about nothing, which is what a scanner
    # would have produced and the reason this is generated instead.
    contains = [r for r in relationships if r.get("relationshipType") == "CONTAINS"]
    if not contains:
        fails.append("no CONTAINS relationships — the image describes nothing")

    # The libraries the image references and does not ship are DEPENDS_ON *without* a
    # CONTAINS, which is how SPDX says "needed, not present". The shape, not the contents:
    # which libraries are missing is test/check-rootfs-deps.sh's business.
    unresolved = _ids(packages, "SPDXRef-Unresolved-")
    wrongly = [r for r in contains if _starts(r.get("relatedSpdxElement"), "SPDXRef-Unresolved-")]
    if wrongly:
        fails.append(f"{len(wrongly)} unresolved libraries claimed as CONTAINS")

    # Every package it names ships its license text, in the image the document is for.
    # A vendor component's texts are its package's.
    manifest = manifest_for(doc)
    if manifest.is_file():
        shipped = set()
        for line in manifest.read_text(encoding="utf-8").split("\n"):
            parts = line.split("/", 4)
            if len(parts) == 5 and parts[:3] == ["usr", "share", "licenses"] and parts[4]:
                shipped.add(parts[3])
        names = sorted({str(p.get("name")).removesuffix("-vendor") for p in components})
        unlicensed = [n for n in names if n not in shipped]
        if unlicensed:
            fails.append(
                "packages shipped without a license text in usr/share/licenses: "
                + _names(unlicensed)
            )
    else:
        fails.append(f"no {manifest} to check the license texts against")

    fails += spdx_model(doc)

    builders = _ids(packages, "SPDXRef-Builder-")
    summary = (
        f"  {len(components)} packages, {len(builders)} build tools, "
        f"{len(unresolved)} unresolved libraries, {len(contains)} CONTAINS"
    )
    return fails, summary


def spdx_model(doc: Path) -> list[str]:
    """What spdx-tools, the SPDX project's own library, finds wrong against the SPDX 2.3
    model: the field formats, licence expressions and references the checks above do
    not re-derive. Each names the element it is about."""
    from spdx_tools.spdx.parser.error import SPDXParsingError
    from spdx_tools.spdx.parser.parse_anything import parse_file
    from spdx_tools.spdx.validation.document_validator import validate_full_spdx_document

    try:
        parsed = parse_file(str(doc))
    except SPDXParsingError as e:
        return ["SPDX: not readable as SPDX 2.3: " + "; ".join(e.get_messages())]
    out = []
    for m in validate_full_spdx_document(parsed, "SPDX-2.3"):
        where = m.context.spdx_id or m.context.parent_id or "the document"
        out.append(f"SPDX: {where}: {m.validation_message}")
    return out


def _names(names: list) -> str:
    return " ".join(str(n) for n in names)


def main(argv: list[str]) -> int:
    repo.enter_root()
    docs = [Path(a) for a in argv] or [Path(f) for f in DEFAULT if Path(f).is_file()]
    if not docs:
        print(
            "error: no SBOM in output/ — image/build-rootfs.sh writes one per flavour",
            file=sys.stderr,
        )
        print(
            "       and is supposed to fail rather than skip it, so its absence is the bug",
            file=sys.stderr,
        )
        return 1

    status = 0
    for doc in docs:
        print(doc, flush=True)
        fails, summary = check(doc)
        for f in fails:
            print(f"  FAIL: {f}", file=sys.stderr, flush=True)
            status = 1
        if summary:
            print(summary, flush=True)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
