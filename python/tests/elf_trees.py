"""ELF trees for the library checks, compiled from a few lines of C, as test/selftest.sh's are.

libfoo comes in two builds with one SONAME, the way a library and the newer header someone
compiled against do:

    new  foo_old, foo_new (unversioned), foo_v1 @FOO_1, foo_v2 @FOO_2
    old  foo_old, foo_v1 @FOO_1: the release before foo_new and FOO_2 existed

and app is linked against new, with a weak foo_maybe no build defines. The trees:

    good       app and new: nothing wrong
    nolib      app alone: libfoo.so.1 is missing
    old        app and old: FOO_2 and foo_new are missing
    alias      libfoo.so.1 only as a link to libfoo-real.so.1 (new)
    alias-old  the same, with old behind the link
    many       the reports' longer forms: six copies of app on old; five programs on a
               libbar.so.2 and one on a libbaz.so.3 the tree does not ship; and one on
               nine symbols libmany's old build lacks

Nothing in what the checks print depends on the host's libc, which every tree copies with
its loader, so the bash versions' output on them is a golden any host can compare to.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

NEW_C = """
int foo_old(void) { return 1; }
int foo_new(void) { return 2; }
int foo_v1(void) { return 3; }
int foo_v2(void) { return 4; }
"""
NEW_MAP = "FOO_1 { global: foo_v1; };\nFOO_2 { global: foo_v2; } FOO_1;\n"
OLD_C = "int foo_old(void) { return 1; }\nint foo_v1(void) { return 3; }\n"
OLD_MAP = "FOO_1 { global: foo_v1; };\n"
APP_C = """
int foo_old(void); int foo_new(void); int foo_v1(void); int foo_v2(void);
__attribute__((weak)) int foo_maybe(void);
int main(void) {
    return foo_old() + foo_new() + foo_v1() + foo_v2() + (foo_maybe ? foo_maybe() : 0);
}
"""
MANY = [f"many_{i}" for i in range(1, 10)]


def available() -> bool:
    return bool(shutil.which("gcc") and shutil.which("readelf"))


def _gcc(*args: str | Path) -> None:
    subprocess.run(["gcc", *map(str, args)], check=True)


def _so(out: Path, soname: str, c: str, src: Path, vmap: str | None = None) -> Path:
    src.mkdir(parents=True, exist_ok=True)
    cfile = src / (out.name + ".c")
    cfile.write_text(c)
    args = ["-shared", "-fPIC", f"-Wl,-soname,{soname}"]
    if vmap is not None:
        mfile = src / (out.name + ".map")
        mfile.write_text(vmap)
        args.append(f"-Wl,--version-script={mfile}")
    out.parent.mkdir(parents=True, exist_ok=True)
    _gcc(*args, cfile, "-o", out)
    return out


def _app(out: Path, c: str, src: Path, libdir: Path, lib: str) -> Path:
    cfile = src / (out.name + ".c")
    cfile.write_text(c)
    _gcc(cfile, f"-L{libdir}", f"-l:{lib}", "-o", out)
    return out


def build(work: Path) -> dict[str, Path]:
    """Every tree under work/, by name."""
    src = work / "src"
    new = _so(src / "new" / "libfoo.so.1", "libfoo.so.1", NEW_C, src, NEW_MAP)
    old = _so(src / "old" / "libfoo.so.1", "libfoo.so.1", OLD_C, src, OLD_MAP)
    app = _app(src / "app", APP_C, src, new.parent, "libfoo.so.1")

    interp = re.search(
        r"Requesting program interpreter: (.*)]",
        subprocess.run(["readelf", "-lW", str(app)], capture_output=True, text=True).stdout,
    ).group(1)
    libc = subprocess.run(
        ["gcc", "-print-file-name=libc.so.6"], capture_output=True, text=True, check=True
    ).stdout.strip()

    def tree(name: str, libfoo: Path | None) -> Path:
        t = work / name
        (t / "usr" / "bin").mkdir(parents=True)
        (t / "usr" / "lib").mkdir(parents=True)
        (t / "lib").symlink_to("usr/lib")
        (t / "lib64").symlink_to("usr/lib")
        shutil.copy(app, t / "usr" / "bin" / "app")
        shutil.copy(libc, t / "usr" / "lib" / "libc.so.6")
        shutil.copy(interp, t / "usr" / "lib" / Path(interp).name)
        if libfoo is not None:
            shutil.copy(libfoo, t / "usr" / "lib" / "libfoo.so.1")
        return t

    trees = {"good": tree("good", new), "nolib": tree("nolib", None), "old": tree("old", old)}
    for name, c, vmap in (("alias", NEW_C, NEW_MAP), ("alias-old", OLD_C, OLD_MAP)):
        t = trees[name] = tree(name, None)
        _so(t / "usr" / "lib" / "libfoo-real.so.1", "libfoo-real.so.1", c, src / name, vmap)
        (t / "usr" / "lib" / "libfoo.so.1").symlink_to("libfoo-real.so.1")

    t = trees["many"] = tree("many", old)
    bindir = t / "usr" / "bin"
    for i in range(1, 7):
        shutil.copy(app, bindir / f"app{i}")
    main_c = "int {f}(void);\nint main(void) {{ return {f}(); }}\n"
    bar = _so(src / "bar" / "libbar.so.2", "libbar.so.2", "int bar(void) { return 0; }", src)
    baz = _so(src / "baz" / "libbaz.so.3", "libbaz.so.3", "int baz(void) { return 0; }", src)
    for i in range(1, 6):
        _app(bindir / f"bar{i}", main_c.format(f="bar"), src, bar.parent, "libbar.so.2")
    _app(bindir / "baz", main_c.format(f="baz"), src, baz.parent, "libbaz.so.3")
    many_new = "".join(f"int {f}(void) {{ return 0; }}\n" for f in MANY)
    many_lib = _so(src / "many" / "libmany.so.1", "libmany.so.1", many_new, src)
    calls = "".join(f"int {f}(void);\n" for f in MANY)
    calls += "int main(void) { return " + " + ".join(f"{f}()" for f in MANY) + "; }\n"
    _app(bindir / "usesmany", calls, src, many_lib.parent, "libmany.so.1")
    _so(t / "usr" / "lib" / "libmany.so.1", "libmany.so.1", "int many_0(void) { return 0; }",
        src / "many-old")  # fmt: skip
    return trees


# (golden name, check, tree, allowlist lines or None): the cases test_elf.py compares
# against what the bash versions printed. None is no allowlist argument at all.
CASES = [
    ("deps-good", "deps", "good", []),
    ("deps-nolib", "deps", "nolib", []),
    ("deps-nolib-allowed", "deps", "nolib", ["libfoo.so.1"]),
    ("deps-nolib-comments", "deps", "nolib", ["# nothing left", ""]),
    ("deps-alias", "deps", "alias", []),
    ("deps-many", "deps", "many", ["# the backlog", "libbar.so.2"]),
    ("deps-many-none", "deps", "many", []),
    ("versions-good", "versions", "good", None),
    ("versions-old", "versions", "old", None),
    ("versions-nolib", "versions", "nolib", None),
    ("versions-many", "versions", "many", None),
    ("resolution-good", "resolution", "good", None),
    ("resolution-old", "resolution", "old", None),
    ("resolution-nolib", "resolution", "nolib", None),
    ("resolution-alias", "resolution", "alias", None),
    ("resolution-alias-old", "resolution", "alias-old", None),
    ("resolution-many", "resolution", "many", None),
]
