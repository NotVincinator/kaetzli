# Host-side scripts: which language for which job

**Status: proposal.** Every script in `test/`, `tools/`, `image/` and `builder/` is bash
today. CLAUDE.md (*Host-side code*) now allows Python and Go for what runs on the host,
in CI or in a builder container; nothing has been rewritten. This page reviews the
scripts against that rule and orders the migration.

Bash remains the only interpreter *in the image*. This is about the repository's tooling.

## The test applied

A script stays bash when its job is running commands and checking exit codes. It moves to
Python when most of its lines work around bash: jq programs longer than the shell around
them, awk for arithmetic or tables, `declare -A` as a data structure, `sed` as a JSON
escaper, `xargs -P` with `export -f` for concurrency, hand-parsed tool output, or argument
parsing and state for a CLI with subcommands.

Go was considered for each and chosen for none: nothing here has to run where Python
cannot (uv installs Python itself, on macOS too), and two general-purpose languages beside
bash would be more to maintain, not less.

## Move to Python, by payoff

### 1. CVE reports: `test/cve-context.sh`, `cve-scan.sh`, `cve-history.sh`

`cve-context.sh` is about 280 lines, most of them a jq program that joins five sources,
plus a curl cache and `xargs -P 8 bash -c` with exported functions. Its Debian version
comparison is a regex approximation (`sub("^.*\\+really"; "")`) that `python-debian`'s
`Version` does properly. In Python it is dataclasses, `requests` with a cache, a thread
pool and one join. `cve-scan.sh` and `cve-history.sh` share the run and artifact
lookups and the summary format, so they move with it.

`cve-workbook.sh` stays as it is: it is a wrapper around grind and its `.rhai` script.

Dependencies: `requests`, `python-debian`.

### 2. SBOM: `image/sbom.sh`, `test/check-sbom.sh`

`sbom.sh` writes SPDX with `printf`, and `jstr` escapes strings with `sed`. It does not
escape newlines or control characters other than tab and CR, and every field is a place
to forget a comma. `check-sbom.sh` exists largely to catch that. Its comment says a JSON serialiser
in `image/Containerfile` was the cost being avoided. Under the new rule that cost is
python3 in a builder-side image, with stdlib `json` only, so the assembly needs no venv.
The checker can then validate against the SPDX model with `spdx-tools`, not just
re-derive a few invariants in jq.

Dependencies: none in the assembly image; `spdx-tools` for the check.

### 3. Size reports: `test/size-history.sh`, `rootfs-size.sh`, `vs-debian-slim.sh`, `oci-trim.sh`

These are awk sparklines, associative arrays of directory sizes and markdown tables, and
`size-history.sh` repeats the "last N green runs on main that still have artifact X" loop.
That loop also appears in `cve-context.sh`, `cve-history.sh`, `fetch-image.sh`,
`reproducible.sh` and `dispatch-ci.sh`. It is the first thing the shared Python module
should hold: one function over `gh run list` / `gh run download`.

Dependencies: none (stdlib and the `gh` CLI).

### 4. Static ELF checks: `check-symbol-resolution.sh`, `check-symbol-versions.sh`, `check-rootfs-deps.sh`

They parse `readelf` text with awk and compute NEEDED closures in shell. `pyelftools`
reads the dynamic section, version tables and symbols directly, with no text format to
misparse. The first version of `check-symbol-resolution.sh` was wrong in the way
`selftest.sh` describes, which is the kind of mistake this rewrite removes. The fixtures
in `selftest.sh` make it safe: every finding has to reproduce, by name. They run on the
CI runner, not in the assembly image.

Dependencies: `pyelftools`.

### 5. Policy checks: `check-licenses.sh`, `kernel-caps.sh`, `kernel-parity.sh`, `kernel-config-diff.sh`, `header-skew.sh`

`check-licenses.sh` splits SPDX expressions by hand; `license-expression` parses them,
`WITH` exceptions included. The kernel scripts read `.config` files into awk tables, which
a dict does better. `header-skew.sh` is a report built on two `declare -A`.

Dependencies: `license-expression`.

### 6. Updates and GitHub automation: `tools/upstream.sh`, `check-updates.sh`, `check-snapshot.sh`, `auto-merge.sh`, `dispatch-ci.sh`, `release-notes.sh`

`upstream.sh` scrapes HTML listings with regexes and sorts versions with knobs from
`env.sh`. `auto-merge.sh` is a state machine that pushes to `main`: age, labels,
checks, rebase, rebuild, fast-forward. It is the script where readability matters most
and where a rewrite is riskiest, so it goes last in this group, after `-n` (dry-run)
output can be compared line by line against the bash version over several nights.
`UPSTREAM_SED` values are sed expressions and stay that way: Python runs `sed -E` on them
rather than translating the knob.

`bump-version.sh` and `bump-snapshot.sh` stay bash: they are `sed -i` on `env.sh` and a
download.

Dependencies: `requests`.

### 7. The qemu harness and its clients: `test/qemu-lib.sh`, the boot tests, `tools/vm.sh`, `tools/k8s-demo.sh`

The biggest payoff and the biggest job. `qemu-lib.sh` drives a console through a fifo
with `await`, marks and timeouts, which is what `pexpect` does. The marks rule in
CLAUDE.md exists because of a bug that a pexpect-based harness would not allow. `vm.sh`
(641 lines) and `k8s-demo.sh` (520) are CLIs with subcommands, config files and state,
and `argparse` plus dataclasses would make them much shorter. With `pytest`, the ~17 boot
tests become test functions sharing fixtures (a booted machine, an ssh session), and
`CONSOLE_BAD` becomes a fixture finaliser.

Two constraints shape it. `tools/boot-vz.sh` runs on macOS and sources `qemu-lib.sh`;
it can keep a small bash copy of what it needs or run the Python harness under uv. And
`tools/boot-qemu.sh` has to keep booting *the same machine* as CI, so the harness must
expose its argv-building for interactive boots. Port it after 1–6 have settled the
module layout, and keep the bash and Python harnesses side by side until every boot test
has moved.

Dependencies: `pexpect`, `pytest`.

### Later, or when touched

- `test/selftest.sh`: becomes pytest once the checks it exercises are Python. Until
  then it stays bash and tests both.
- `test/check-doc-links.sh`, `check-image-files.sh`: small and fine, but they parse
  formats (markdown, glob manifests) that Python handles better. Move when touched.
- `image/build-extension.sh`: mostly commands. Its SBOM part follows item 2.

## Stay bash

| script | why |
| --- | --- |
| `build.sh`, `builder/build-package.sh`, `packages/*/build.sh`, `env.sh` | sourced by package builds; the vocabulary is shell functions, and `env.sh` is read by bash everywhere |
| `image/build-rootfs.sh` | mostly cp, tar, setcap, mkfs.erofs and veritysetup in order. 987 lines is too long; split the reports and SBOM out (items 2, 3) and leave the commands |
| `tools/lib.sh` | the bash scripts that remain still need it; the Python module is its counterpart, not its replacement |
| `tools/prep.sh`, `fetch-sources.sh`, `build-image.sh`, `build-extension.sh`, `publish-oci.sh`, `merge-staging.sh`, `clean.sh`, `image-tags.sh`, `build-node-e2e.sh` | podman, tar and file operations in sequence |
| `tools/check-patches.sh`, `sync-patches.sh`, `patch-cves.sh` | patch and git invocations; `sync-patches.sh` is the largest and could move later |
| `tools/boot-qemu.sh`, `boot-firecracker.sh`, `boot-vz.sh`, `ssh.sh`, `demo.sh` | thin wrappers that exec a VMM or ssh; `boot-vz.sh` must run on macOS's bash 3.2 |
| `test/check-tree-hygiene.sh` | runs inside the assembly image; a few `find` calls |
| `test/reproducible.sh`, `prebuilt.sh`, `oci.sh` | podman and git orchestration; they move only if the harness (item 7) gives them something |
| inline `run:` steps in `.github/workflows/` | short; a step that outgrows a few lines becomes a script, and then this page applies |

## How a migration lands

One script per pull request, behaviour unchanged. The proof is the same output before
and after: byte-identical reports, SBOMs and job summaries for the same inputs, the same
exit codes, and every `selftest.sh` fixture still failing with what is wrong named. Then
the bash file is deleted in the same pull request and the `Commands` list in CLAUDE.md is
updated. The CI step that runs it gains `astral-sh/setup-uv` with a pinned version.
