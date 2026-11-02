"""kaetzli.updates.versort against GNU sort -V itself, which the shell scripts used."""

import random
import shutil
import subprocess

import pytest

from kaetzli.updates import versort

CASES = [
    ["2.10", "2.9", "2.9.1", "10.0", "1.0"],
    ["10.5p1", "10.5", "10.4p2", "10.10p1"],
    ["2026e", "2026a", "2025z", "2026"],
    ["20251010", "20250101+nmu1", "20250101"],
    ["2026_01_20.a1b2c3d", "2026_01_20.386b5f5", "2025_12_31.ffffff0"],
    ["v6.x/", "v10.x/", "v7.x/", "v3.0/", "v2.6/"],
    ["2.86/", "2.84/", "2.9/", "2.100/"],
    ["1.0", "1.00", "1.0~rc1", "1.0a", "1.0.0"],
    ["0.197", "0.19", "0.2", "0.200"],
]


def gnu_sort(values, unique=False):
    args = ["sort", "-Vu" if unique else "-V"]
    r = subprocess.run(
        args,
        input="".join(f"{v}\n" for v in values),
        capture_output=True,
        text=True,
        env={"LC_ALL": "C"},
        check=True,
    )
    return r.stdout.splitlines()


needs_sort = pytest.mark.skipif(
    not shutil.which("sort")
    or b"GNU" not in subprocess.run(["sort", "--version"], capture_output=True).stdout,
    reason="GNU sort is the reference",
)


@needs_sort
@pytest.mark.parametrize("values", CASES)
@pytest.mark.parametrize("unique", [False, True])
def test_the_order_is_gnu_sorts(values, unique):
    assert versort.sort(values, unique) == gnu_sort(values, unique)


@needs_sort
def test_random_versions_order_as_gnu_sort_does():
    rng = random.Random(1)
    alphabet = "0123456789.-~_pabz+"
    values = ["".join(rng.choice(alphabet) for _ in range(rng.randint(1, 8))) for _ in range(3000)]
    assert versort.sort(values) == gnu_sort(values)


@pytest.mark.parametrize(
    ("current", "latest", "newer"),
    [
        ("2.9", "2.10", True),
        ("2.10", "2.9", False),
        ("1.0", "1.0", False),
        ("10.5p1", "10.5p2", True),
        ("2026a", "2026e", True),
        ("1.0", "1.0.1", True),
    ],
)
def test_newer(current, latest, newer):
    assert versort.newer(current, latest) is newer
