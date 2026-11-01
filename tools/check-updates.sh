#!/bin/bash
# Compare the version each package is pinned to against what upstream has released:
#
#     ./tools/check-updates.sh              # every package
#     ./tools/check-updates.sh bash glibc   # only these
#     ./tools/check-updates.sh --json       # machine-readable, for the update workflow
#
# Where to look for versions is declared per package in its env.sh; see tools/upstream.sh.
# A candidate is only reported once its tarball has been confirmed to exist at the URL
# env.sh would download it from, so a project that changes its file naming shows up as
# an error here instead of as a pull request that fails to build.
#
# A package can have up to three things to keep current, each reported on its own line
# and as its own JSON entry, told apart by "kind":
#
#   version   the release itself (VERSION)                 tools/bump-version.sh
#   vendor    a second tarball with a VENDOR_VERSION of     tools/bump-version.sh --vendor
#             its own, shown as <pkg>/<VENDOR_NAME>
#   patches   an upstream patch series (UPSTREAM_PATCHES),  tools/sync-patches.sh
#             shown as <VERSION>-p<n>, n patches
set -euo pipefail

cd "$(dirname "$0")/.."
source tools/lib.sh

JSON=false
PACKAGES=()

for arg in "$@"; do
    case "$arg" in
        --json) JSON=true ;;
        -h|--help) sed -n '2,21p' "$0" | sed 's/^# \?//'; exit 0 ;;
        -*) echo "error: unknown option: $arg" >&2; exit 1 ;;
        # Accept both `coreutils` and the path a shell tab-completes to.
        *) PACKAGES+=("$arg") ;;
    esac
done

if [ ${#PACKAGES[@]} -eq 0 ]; then
    mapfile -t PACKAGES < <(all_packages)
fi

# The URL a package would download if its env.sh said VERSION=$2. env.sh derives
# PACKAGE, TARBALL and URL from VERSION, so rewriting that one line is all an update
# ever has to do — both here and in the pull request the workflow opens.
#
# url_for_version <pkg> <version> [VENDOR_] — the same for the vendor tarball.
url_for_version() (
    PKG="$1"
    eval "$(sed -E "s/^${3:-}VERSION=.*/${3:-}VERSION=\"$2\"/" "packages/$PKG/env.sh")"
    if [ -n "${3:-}" ]; then printf '%s\n' "$VENDOR_URL"; else printf '%s\n' "$URL"; fi
)

# newer <current> <latest> — whether latest sorts after current (sort -V, so 2.10 counts
# as newer than 2.9 and a downgrade is never proposed).
newer() {
    [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1)" = "$2" ]
}

# report <kind> <label> <current> <latest> <url> [release-notes]
report() {
    $JSON || printf '%-12s %-10s -> %-10s %s\n' "$2" "$3" "$4" "$5"
    updates+=("$(jq -nc --arg k "$1" --arg p "$PKG" --arg c "$3" --arg l "$4" --arg u "$5" \
        --arg n "${6:-}" --arg name "${2#"$PKG"/}" \
        '{package:$p, kind:$k, current:$c, latest:$l, url:$u}
         + (if $k == "vendor" then {component:$name} else {} end)
         + (if $n == "" then {} else {release_notes:$n} end)')")
}

# check_vendor — the second tarball, when it has a version of its own.
check_vendor() {
    local name current latest url
    { read -r name; read -r current; } < <(env_get "$PKG" VENDOR_NAME VENDOR_VERSION)
    [ -n "$current" ] || return 0
    name="$PKG/${name:-vendor}"
    if ! latest=$(./tools/upstream.sh --vendor "$PKG"); then
        $JSON || printf '%-12s %-10s %s\n' "$name" "$current" "ERROR: upstream lookup failed"
        failed=true; return 0
    fi
    if ! newer "$current" "$latest"; then
        $JSON || printf '%-12s %-10s up to date\n' "$name" "$current"
        return 0
    fi
    url=$(url_for_version "$PKG" "$latest" VENDOR_)
    if ! curl -fsIL --max-time 60 --retry 2 -o /dev/null "$url"; then
        $JSON || printf '%-12s %-10s %s\n' "$name" "$current" "ERROR: $latest announced but $url is not downloadable"
        failed=true; return 0
    fi
    report vendor "$name" "$current" "$latest" "$url"
}

# check_patches <version> — the upstream patch series against patches/upstream/.
check_patches() {
    local index ours theirs
    index=$(env_get "$PKG" UPSTREAM_PATCHES)
    [ -n "$index" ] || return 0
    ours=$(find "packages/$PKG/patches/upstream" -type f 2>/dev/null | wc -l)
    if ! theirs=$(./tools/sync-patches.sh --list "$PKG" | wc -l); then
        $JSON || printf '%-12s %-10s %s\n' "$PKG" "$1-p$ours" "ERROR: patch listing failed"
        failed=true; return 0
    fi
    if [ "$theirs" -le "$ours" ]; then
        $JSON || printf '%-12s %-10s patches up to date\n' "$PKG" "$1-p$ours"
        return 0
    fi
    report patches "$PKG" "$1-p$ours" "$1-p$theirs" "$index"
}

updates=()
failed=false

for PKG in "${PACKAGES[@]}"; do
    if ! PKG=$(package_name "$PKG"); then
        failed=true
        continue
    fi

    { read -r current; read -r local_source; read -r follows; } < <(env_get "$PKG" VERSION LOCAL_SOURCE FOLLOWS)

    # A package whose source is in this repository has no upstream to compare against —
    # its VERSION is ours, and nothing announces releases of it.
    if [ -n "$local_source" ]; then
        $JSON || printf '%-12s %-10s local source, no upstream\n' "$PKG" "$current"
        continue
    fi

    # A package built from another one's tarball (linux-tools from the kernel's) takes
    # its VERSION from that package's env.sh, so the update is that package's to
    # propose. Asking here too would open the same bump twice, and the second pull
    # request would have no VERSION line to rewrite. Its own second tarball is still its
    # own (libtraceevent).
    if [ -n "$follows" ]; then
        $JSON || printf '%-12s %-10s follows %s\n' "$PKG" "$current" "$follows"
        check_vendor
        continue
    fi

    check_vendor

    if ! latest=$(./tools/upstream.sh "$PKG"); then
        $JSON || printf '%-12s %-10s %s\n' "$PKG" "$current" "ERROR: upstream lookup failed"
        failed=true
        continue
    fi

    if ! newer "$current" "$latest"; then
        $JSON || printf '%-12s %-10s up to date\n' "$PKG" "$current"
        # Only now: a new release starts a new series, which its bump syncs anyway.
        check_patches "$current"
        continue
    fi

    url=$(url_for_version "$PKG" "$latest")

    if ! curl -fsIL --max-time 60 --retry 2 -o /dev/null "$url"; then
        $JSON || printf '%-12s %-10s %s\n' "$PKG" "$current" "ERROR: $latest announced but $url is not downloadable"
        failed=true
        continue
    fi

    report version "$PKG" "$current" "$latest" "$url" "$(./tools/release-notes.sh "$PKG" "$latest" 2>/dev/null || true)"
done

if $JSON; then
    if [ ${#updates[@]} -eq 0 ]; then
        echo '[]'
    else
        printf '%s\n' "${updates[@]}" | jq -sc .
    fi
fi

if $failed; then
    exit 1
fi
