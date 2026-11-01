#!/usr/bin/env bash
# Make packages/<pkg>/patches/upstream/ exactly the patch series upstream publishes for the
# pinned VERSION:
#
#     ./tools/sync-patches.sh bash          # download what is missing, drop what is gone
#     ./tools/sync-patches.sh --list bash   # print upstream's series, change nothing
#
# For a project that ships fixes as patches against a release rather than as a new
# release — GNU bash's bash53-001, -002, … — the release tarball alone is not the current
# upstream. env.sh says where the series is:
#
#   UPSTREAM_PATCHES       URL of the directory listing the patches
#   UPSTREAM_PATCH_REGEX   ERE matching one patch's file name (and not its .sig)
#   UPSTREAM_PATCH_STRIP   the -p level they apply with (default 1; bash's are -p0)
#
# The patches are committed, so a build never needs the network for them, and they go
# into the sources image beside the tarballs (tools/prep.sh). Like tools/bump-version.sh,
# this trusts what upstream serves at the moment of the sync; git is the pin afterwards,
# and a series that changed under us shows up as a diff of a file already committed.
#
# tools/check-updates.sh proposes a sync when upstream has more patches than we do, the
# update workflow runs this to make the pull request, and tools/bump-version.sh runs it
# after every version bump of such a package — a new release starts a new series.
set -euo pipefail

cd "$(dirname "$0")/.."
source tools/lib.sh

list_only=
[ "${1:-}" = --list ] && { list_only=1; shift; }
[ -n "${1:-}" ] || { echo "usage: ${0##*/} [--list] <package>" >&2; exit 2; }

PKG=$(package_name "$1")
mapfile -t v < <(env_get "$PKG" UPSTREAM_PATCHES UPSTREAM_PATCH_REGEX)
index=${v[0]:-} regex=${v[1]:-}
if [ -z "$index" ] || [ -z "$regex" ]; then
    echo "error: packages/$PKG/env.sh sets no UPSTREAM_PATCHES/UPSTREAM_PATCH_REGEX" >&2
    exit 1
fi
index="${index%/}/"

# Bounded by quotes or '>' on both sides, so bash53-001.sig never matches as bash53-001.
# A listing that is missing entirely is a 404 and fails here; an existing listing with
# nothing in it is a release with no patches yet, which is normal.
page=$(fetch "$index")
names=$(printf '%s\n' "$page" | grep -oE "[\">]$regex[\"<]" | tr -d '"<>' | LC_ALL=C sort -u || true)

if [ -n "$list_only" ]; then
    [ -z "$names" ] || printf '%s\n' "$names"
    exit 0
fi

dest="packages/$PKG/patches/upstream"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

while read -r name; do
    [ -n "$name" ] || continue
    if [ -f "$dest/$name" ]; then
        cp "$dest/$name" "$tmp/$name"
    else
        echo "  $PKG: fetching $index$name"
        "${CURL_DOWNLOAD[@]}" -o "$tmp/$name" "$index$name"
    fi
done <<< "$names"

rm -rf "$dest"
if [ -n "$(ls -A "$tmp")" ]; then
    mkdir -p "$dest"
    cp "$tmp"/* "$dest/"
fi
echo "$PKG: $(ls "$dest" 2>/dev/null | wc -l) upstream patches for $(env_get "$PKG" VERSION)"
