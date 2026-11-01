import os
import time

import pytest

from kaetzli.http_cache import Cache, Response


class FakeFetch:
    def __init__(self, status=200, body=b'{"ok": true}'):
        self.status, self.body, self.urls = status, body, []

    def __call__(self, url, timeout):
        self.urls.append(url)
        if self.status is None:
            raise OSError("unreachable")
        return Response(self.status, self.body)


@pytest.fixture
def path(tmp_path):
    return tmp_path / "x.json"


def age(path, minutes):
    t = time.time() - minutes * 60
    os.utime(path, (t, t))


def test_fetches_and_keeps(path):
    fetch = FakeFetch()
    assert Cache(fetch=fetch).get(path, "https://x/1")
    assert path.read_bytes() == b'{"ok": true}'
    assert fetch.urls == ["https://x/1"]


def test_fresh_is_not_asked_again(path):
    path.write_text("old")
    fetch = FakeFetch()
    assert Cache(fetch=fetch, max_age_minutes=60).get(path, "https://x/1")
    assert fetch.urls == []
    assert path.read_text() == "old"


def test_stale_is_refetched(path):
    path.write_text("old")
    age(path, 61)
    assert Cache(fetch=FakeFetch(), max_age_minutes=60).get(path, "https://x/1")
    assert path.read_text() == '{"ok": true}'


def test_a_404_is_remembered_as_empty_json(path):
    assert Cache(fetch=FakeFetch(status=404)).get(path, "u")
    assert path.read_text() == "{}\n"


def test_any_other_failure_keeps_the_old_copy(path):
    path.write_text("old")
    age(path, 2000)
    assert Cache(fetch=FakeFetch(status=500)).get(path, "u")
    assert path.read_text() == "old"
    assert Cache(fetch=FakeFetch(status=None)).get(path, "u")


def test_failure_with_nothing_cached(path):
    assert not Cache(fetch=FakeFetch(status=500)).get(path, "u")
    assert not path.exists()
    assert not path.with_name(path.name + ".tmp").exists()


def test_an_empty_file_is_not_a_cache_hit(path):
    path.write_text("")
    fetch = FakeFetch()
    assert Cache(fetch=fetch).get(path, "u")
    assert fetch.urls == ["u"]


def test_offline_uses_any_age_and_never_asks(path):
    fetch = FakeFetch()
    c = Cache(fetch=fetch, offline=True, max_age_minutes=1)
    assert not c.get(path, "u")
    path.write_text("old")
    age(path, 10_000)
    assert c.get(path, "u")
    assert fetch.urls == []
