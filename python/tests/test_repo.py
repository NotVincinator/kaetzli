import os

import pytest

from kaetzli import repo


class TestNormalizeArch:
    @pytest.mark.parametrize(
        ("given", "arch"),
        [("x86_64", "amd64"), ("amd64", "amd64"), ("aarch64", "arm64"), ("arm64", "arm64")],
    )
    def test_either_spelling(self, given, arch):
        assert repo.normalize_arch(given) == arch

    def test_empty_is_the_hosts(self, monkeypatch):
        monkeypatch.setattr(os, "uname", lambda: os.uname_result(("", "", "", "", "aarch64")))
        assert repo.normalize_arch("") == "arm64"
        assert repo.normalize_arch(None) == "arm64"

    def test_unsupported_is_an_error(self):
        with pytest.raises(repo.UnsupportedArch, match="unsupported architecture: riscv64"):
            repo.normalize_arch("riscv64")


class TestTheRealRepository:
    """These read the checkout itself: env.sh is bash, and only bash reads it."""

    def test_root_holds_build_sh(self):
        assert (repo.ROOT / "build.sh").is_file()
        assert (repo.ROOT / "tools" / "lib.sh").is_file()

    def test_all_packages_in_directory_order(self):
        pkgs = repo.all_packages()
        assert "glibc" in pkgs
        assert pkgs == sorted(pkgs)

    def test_env_get_reads_through_bash(self):
        license_, missing = repo.env_get("glibc", "LICENSE", "NO_SUCH_VARIABLE")
        assert "LGPL" in license_
        assert missing == ""

    def test_env_get_does_not_leak_between_packages(self):
        # glibc sets NO_SYSROOT=1; a package that does not must not see it.
        (glibc,) = repo.env_get("glibc", "NO_SYSROOT")
        (bash,) = repo.env_get("bash", "NO_SYSROOT")
        assert (glibc, bash) == ("1", "")

    def test_env_get_all_reads_every_package_once(self):
        cpes = repo.env_get_all("CPE")
        assert set(cpes) == set(repo.all_packages())
        assert "cpe:2.3:a:gnu:glibc" in cpes["glibc"]

    def test_lib_constant(self):
        assert int(repo.lib_var("KAETZLI_SOURCE_DATE_EPOCH")) == repo.SOURCE_DATE_EPOCH
