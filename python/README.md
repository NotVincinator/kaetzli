# python/

The `kaetzli` package: the code behind the Python scripts in `test/` and `tools/`, its
tests, and the one lock file for all of them. None of it ever reaches an image.

```
launch.py            what each entry point calls: stdlib only, execs uv run --locked
src/kaetzli/         shared: repo (env.sh through bash), report (stdout + job summary),
                     gh (CI runs and artifacts), http_cache
src/kaetzli/cve/     the CVE reports: scan, context, history, and what they share
src/kaetzli/size/    the size reports: budget (rootfs-size), slim (vs-debian-slim),
                     history (size-history), trim (oci-trim), and sizes, their parser
src/kaetzli/sbom_check.py
                     test/check-sbom.py: what the SBOM says
tests/               pytest; fixtures/ holds real data cut down, and the bash versions'
                     output the Python had to reproduce
```

One Python file is outside the package: `image/sbom.py`, which writes the SBOM in the
assembly container. That has python3 and no venv, so it is stdlib only and imports
nothing from `kaetzli`; `tests/test_sbom_write.py` runs it the way the container does,
and the lint covers it as `../image/*.py`.

## Running

Install [uv](https://docs.astral.sh/uv/getting-started/installation/). Nothing else:
uv fetches the pinned Python and makes `python/.venv` from `uv.lock` on first use.

```sh
./test/cve-scan.py output          # an entry point, from any directory
cd python
uv run pytest                      # the tests
uv run ruff check . ../image/*.py && uv run ruff format --check . ../image/*.py
```

Never `pip install` anything, into the venv or elsewhere. A dependency is a line in
`pyproject.toml` and a `uv lock`, argued in the pull request like a package
(CLAUDE.md, *Host-side code*). Dependabot proposes updates to the lock once a release is
two weeks old; the Python workflow tests them.

## Adding a script

1. The code is a module under `src/kaetzli/` with a `main(argv)`, run through
   `kaetzli.report.run`, so a `Note` ends the report with exit 0.
2. The entry point in `test/` or `tools/` is the five lines `test/cve-scan.py` is.
3. Tests first: they fail, then the module makes them pass. A port of a bash script
   also gets a golden test: the bash version's output on fixtures, committed, which the
   Python must reproduce byte for byte, deliberate fixes excepted and said so.
