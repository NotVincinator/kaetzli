# Patches

Implemented. A package can carry patches against its upstream source. They live in git
beside the package, are applied once when the tarball is extracted, and need no network
at build time.

```
packages/<pkg>/patches/
    upstream/          upstream's patch series (bash53-001, …) or release branch, applied first
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

### From a release branch

glibc backports fixes, security fixes above all, to `release/2.44/master` and rarely tags
a point release for them. The branch is followed as a series too:

```sh
UPSTREAM_PATCH_GIT="https://sourceware.org/git/glibc.git"
UPSTREAM_PATCH_BRANCH="release/${VERSION}/master"
UPSTREAM_PATCH_BASE="glibc-${VERSION}"   # the tag the tarball was cut from
```

`sync-patches.sh` writes `git format-patch <base>..<branch>`, so the tarball plus the
series is the branch's tree at its head. That head is the `From <sha>` line of the last
patch. Only the commits since the tag are fetched (about 40 seconds, 50 MB), not the
repository. `--list` first compares the branch head with that line, so a check with
nothing new costs one `git ls-remote`.

A glibc sync rebuilds every package, because each one is compiled against glibc.

### How a series is kept current, and why that is safe

Nobody imports patches by hand. Every night `update-packages.yml` runs
`check-updates.sh`, which reports a longer series as `2.44-p66 -> 2.44-p67`. The workflow
then runs `sync-patches.sh` and opens a pull request that lists the new patches and the
CVEs they fix. CI builds and boots it, and `auto-merge.yml` merges it after 24 hours if
it is green and nobody labelled it `hold`. A version bump starts a new series
(`bump-version.sh` calls `sync-patches.sh --new-series`).

What stops a bad patch from getting that far:

- **Append-only.** Every committed patch must come back byte for byte, and new ones must
  sort after them. A rewritten branch, a replaced file or a changed server fails the
  sync (exit 3), so the workflow opens nothing and the run is red.
- **Signatures, where upstream signs.** `packages/<pkg>/upstream-key.asc` pins the key.
  Every newly fetched patch must verify against it with `gpgv`, not against a key the
  server offers. bash (Chet Ramey) and ncurses (Thomas E. Dickey) sign theirs; both keys
  were checked against two independent sources when pinned.
- **Git history, where upstream does not sign.** glibc and gcc branch commits are
  unsigned. Each patch carries its commit id, and append-only means the branch can only
  have moved forward.
- **Patches are data.** Patches apply with `--fuzz=0`. A preamble meant to be fed to `sh`
  (ncurses: "remove these files first") is honoured only for `rm -f` of paths inside the
  tree; anything else in it fails the build.
- **Every patch is in git** and in the pull request diff, the cache key and the sources
  image, so what was built is always what was reviewed.

More options for series on a server:

```sh
UPSTREAM_PATCH_SIG=".asc"                                  # signature suffix, default .sig
UPSTREAM_PATCH_SKIP="ncurses-6\.6-20251230\.patch\.gz"    # in the tarball already
```

A name ending in `.gz` is verified compressed, as it was signed, and committed
decompressed.

## CVEs fixed by patches

A scanner matches versions: glibc 2.44 is glibc 2.44 to it, however many fixes are on
top. So the build says what its patches fix, and the scan believes it:

- `tools/patch-cves.sh <pkg>` lists the CVEs a package's patches fix. It reads each
  patch's message (never the diff) and `patches/upstream.cves`, which `sync-patches.sh`
  writes from glibc's advisories. For one of our own patches, name the CVE in its message,
  for example with a `CVE: CVE-2026-12345` line.
- `build.sh` records them, and the SBOM carries each as an SPDX `fix` reference on its
  package.
- `test/cve-scan.sh` turns those into OpenVEX (`output/cve/<sbom>.vex.json`) and passes it
  to grype. A patched CVE is then not counted as open. The job summary lists patched CVEs
  separately, and the CVE workbook marks them `patched` in a Status column; its severity
  counts are open findings only.

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
