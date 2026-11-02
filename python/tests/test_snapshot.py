"""tools/check-snapshot.py: the Debian snapshot pin against Docker Hub's dated sid tags.

The bash version's output was compared live (up to date, --json, STALE_DAYS=1 and an
unknown option): identical. Here the clock and Docker Hub are injected.
"""

import json
from datetime import UTC, datetime

import pytest

from kaetzli.updates import snapshot
from kaetzli.updates.http import FetchError

NOW = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)


def hub(*names):
    return json.dumps({"results": [{"name": n} for n in names]})


class Hub:
    def __init__(self, body=None):
        self.body = body

    def get(self, url):
        assert url == snapshot.HUB_TAGS
        if self.body is None:
            raise FetchError(f"{url}: 503")
        return self.body


@pytest.fixture
def tree(tmp_path):
    for d in ("builder", "image"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "Containerfile").write_text(
            "FROM x\nARG SNAPSHOT=20261027  # the pin\nARG SNAPSHOT\nARG SNAPSHOT=20990101\n"
        )
    return tmp_path


def run(tree, argv, body, capsys, stale=90):
    rc = snapshot.check(argv, tree, Hub(body), now=NOW, stale_days=stale)
    out, err = capsys.readouterr()
    return rc, out, err


def test_up_to_date(tree, capsys):
    body = hub("sid-20261020", "sid-20261027", "sid-20261027-slim", "sid-slim", "sid")
    assert run(tree, [], body, capsys) == (
        0,
        "debian-snapshot  20261027   up to date (6 days old)\n",
        "",
    )
    assert run(tree, ["--json"], body, capsys) == (0, "[]\n", "")


def test_a_newer_image(tree, capsys):
    body = hub("sid-20261103", "sid-20261027", "sid-20261110-slim")
    url = "https://hub.docker.com/_/debian/tags?name=sid-20261103"
    assert run(tree, [], body, capsys) == (
        0,
        f"debian-snapshot  20261027   -> 20261103   {url}\n",
        "",
    )
    _, out, _ = run(tree, ["--json"], body, capsys)
    assert out == (
        '[{"package":"debian-snapshot","current":"20261027","latest":"20261103",'
        f'"url":"{url}"}}]\n'
    )


def test_stale_is_said_first_and_on_stderr(tree, capsys):
    rc, out, err = run(tree, [], hub("sid-20261027"), capsys, stale=6)
    assert rc == 0 and "up to date" in out
    assert err == (
        "warning: the Debian snapshot pin is 6 days old (20261027)\n"
        "         bumps are proposed automatically, so this means they are not landing\n"
    )


def test_the_two_pins_must_agree(tree, capsys):
    (tree / "image" / "Containerfile").write_text("ARG SNAPSHOT=20261020\n")
    rc, out, err = run(tree, [], hub("sid-20261027"), capsys)
    assert (rc, out) == (1, "")
    assert "builder/Containerfile is pinned to 20261027 but image/Containerfile to 20261020" in err


def test_no_pin(tree, capsys):
    (tree / "image" / "Containerfile").write_text("FROM x\n")
    assert run(tree, [], hub(), capsys)[0] == 1


@pytest.mark.parametrize("body", [None, hub("sid", "sid-slim"), "not json"])
def test_no_dated_tags_is_an_error(tree, capsys, body):
    rc, out, err = run(tree, ["--json"], body, capsys)
    assert (rc, out) == (1, "")
    assert err == "error: could not list dated sid tags on Docker Hub\n"


def test_options(tree, capsys):
    assert run(tree, ["--nope"], hub(), capsys) == (2, "", "error: unknown option: --nope\n")
    rc, out, _ = run(tree, ["--help"], hub(), capsys)
    assert rc == 0 and "check-snapshot.py --json" in out
