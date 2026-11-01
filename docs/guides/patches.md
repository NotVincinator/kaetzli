# Patches

Implemented. A package can carry patches against its upstream source. They live in git
beside the package, are applied once when the tarball is extracted, and need no network
at build time.

```
packages/<pkg>/patches/
    upstream/          a patch series upstream publishes (bash53-001, …), applied first
    0001-<topic>.patch our own, applied after, in file-name order
```

Patches are part of the build input everywhere it is pinned: the extraction stamp
(`packages/<pkg>/.<PACKAGE>.patches`), the CI cache key, the sources image, which carries
them as `/sources/patches/<pkg>/` and has them in its tag, and the SBOM, which lists each
patch by name and SHA-256 in its package's `comment`.

## Our own patches

Use these for a fix upstream has committed but not yet released, such as gzip 1.15's
aarch64 build fix (`packages/gzip/patches/`). Prefer upstream's commit, verbatim, over a
patch of our own: it says where it came from, and when the next release includes it the
patch stops applying, so you notice.

They are `-p1` (`a/` and `b/` prefixes). The two easiest ways to get one:

```sh
# an upstream commit, as a patch file (cgit, GitHub and GitLab all serve one)
curl -fL 'https://git.savannah.gnu.org/cgit/gzip.git/patch/?id=<commit>' \
    -o packages/gzip/patches/0001-<subject>.patch

# your own change to an unpacked tree
cd output/patch-check/<pkg>/src && git init -q && git add -A && git commit -qm base
#   ...edit...
git diff > ../../../../packages/<pkg>/patches/0002-<topic>.patch
```

Patches apply with `--fuzz=0`: one that only applies with shifted context has to be
rebased, not guessed at. Remove a patch once the release it was waiting for is pinned.
The build of that bump fails until you do.

## Upstream patch series

Some projects ship fixes as numbered patches against a release instead of new tarballs.
GNU bash does: `bash-5.3` plus `bash53-001`…`020` is current upstream. In `env.sh`:

```sh
UPSTREAM_PATCHES="https://ftp.fau.de/gnu/bash/${PACKAGE}-patches/"  # the listing
UPSTREAM_PATCH_REGEX="bash${VERSION//./}-[0-9]{3}"                   # one patch's name
UPSTREAM_PATCH_STRIP=0                                               # -p level, default 1
```

`patches/upstream/` belongs to `tools/sync-patches.sh`, which makes it exactly upstream's
series for the pinned `VERSION`. `tools/check-updates.sh` reports a longer series as
`5.3-p20 -> 5.3-p21`, and the update workflow opens a pull request for it like for a
release. A version bump syncs too, because a new release starts a new series.

```sh
./tools/sync-patches.sh --list bash   # what upstream has
./tools/sync-patches.sh bash          # make patches/upstream/ match it
```

## Test that patches apply

```sh
./tools/check-patches.sh                       # every package with patches
./tools/check-patches.sh gzip                  # one package, against its pinned tarball
./tools/check-patches.sh --version 1.16 gzip   # against a release not pinned yet
KEEP=1 ./tools/check-patches.sh gzip           # keep output/patch-check/gzip/src
```

This runs the extraction step of `./build.sh` on its own: it unpacks the tarball and
applies the patches in the builder image, then stops. It takes seconds and does not touch
`packages/` or `staging/`. It needs the tarball and the builder image; the first run
fetches both. `patch` comes from the builder, so the host needs none.

`--version` answers the question a bump raises before you make it: do our patches still
apply, or has upstream merged them? That tarball is not pinned yet, so it is downloaded
unverified into `output/patch-check/`.

A full `./build.sh <pkg>` applies the same patches the same way. Changing, adding or
removing one re-extracts the tree automatically.
