"""tools/auto-merge.py: the scenarios in automerge_harness, against the bash version.

Each scenario runs dry (-n) and for real through fake git, gh and date; the Python must
print the same transcript, exit the same, and make the same git, gh and dispatch-ci calls
in the same order as the bash tools/auto-merge.sh did (expected/). The decisions are also
tested on their own below.
"""

import time

import pytest
from automerge_harness import BIN, EXPECTED, SCENARIOS, checkout, materialize, normalize

from kaetzli import automerge

CASES = [(name, mode) for name in SCENARIOS for mode in ("dry", "wet")]


@pytest.mark.parametrize(("name", "mode"), CASES)
def test_the_transcript_is_the_bash_versions(name, mode, tmp_path, monkeypatch, capfd):
    root = checkout(tmp_path)
    fake = tmp_path / "fake"
    for k, v in materialize(name, fake, time.time()).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("PATH", f"{BIN}:{__import__('os').environ['PATH']}")
    monkeypatch.delenv("MIN_AGE_HOURS", raising=False)
    slept = []
    hour = SCENARIOS[name].get("hour")

    rc = automerge.main(
        ["-n"] if mode == "dry" else [],
        root=root,
        hour=(lambda: hour) if hour is not None else (lambda: 0),
        sleep=slept.append,
    )

    out, err = capfd.readouterr()
    expected = EXPECTED / name / mode
    assert normalize(out, fake) == (expected / "stdout.txt").read_text()
    assert normalize(err, fake) == (expected / "stderr.txt").read_text()
    assert rc == int((expected / "rc").read_text())
    assert normalize((fake / "log").read_text(), fake) == (expected / "log.txt").read_text()
    if (name, mode) == ("green", "wet"):
        assert slept == [5]  # GitHub noticed the merge on the second look


NOW = 1_800_000_000


def iso(seconds_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - seconds_ago))


class TestChecksState:
    def test_none(self):
        assert automerge.checks_state([], NOW) == "none"

    def test_green_counts_neutral_and_skipped(self):
        rollup = [
            {"status": "COMPLETED", "conclusion": "SUCCESS", "startedAt": iso(60)},
            {"status": "COMPLETED", "conclusion": "NEUTRAL", "startedAt": iso(60)},
            {"status": "COMPLETED", "conclusion": "SKIPPED", "startedAt": iso(60)},
            {"state": "SUCCESS"},  # a status context: no status, no startedAt
        ]
        assert automerge.checks_state(rollup, NOW) == "green"

    def test_a_failure_wins_over_a_running_check(self):
        rollup = [
            {"status": "IN_PROGRESS", "conclusion": "", "startedAt": iso(60)},
            {"status": "COMPLETED", "conclusion": "CANCELLED", "startedAt": iso(60)},
        ]
        assert automerge.checks_state(rollup, NOW) == "failed"

    def test_a_pending_status_is_not_done(self):
        assert automerge.checks_state([{"state": "PENDING", "startedAt": iso(60)}], NOW) == (
            "pending"
        )

    def test_running_for_six_hours_is_a_dead_reporter(self):
        rollup = [
            {"status": "COMPLETED", "conclusion": "SUCCESS", "startedAt": iso(60)},
            {"status": "IN_PROGRESS", "conclusion": "", "startedAt": iso(6 * 3600)},
        ]
        assert automerge.checks_state(rollup, NOW) == "stale"
        rollup[1]["startedAt"] = iso(6 * 3600 - 1)
        assert automerge.checks_state(rollup, NOW) == "pending"

    def test_a_timestamp_jq_would_not_read_is_an_error(self):
        with pytest.raises(ValueError):
            automerge.checks_state([{"status": "COMPLETED", "startedAt": "2026-11-02"}], NOW)


@pytest.mark.parametrize(
    ("event", "hour", "night"),
    [("schedule", 21, False), ("schedule", 22, True), ("schedule", 0, True),
     ("schedule", 4, True), ("schedule", 5, False), ("schedule", 12, False),
     ("workflow_dispatch", 12, True), ("", 12, True)],
)  # fmt: skip
def test_at_night(event, hour, night):
    assert automerge.at_night(event, hour) is night


def test_updates_oldest_first_and_only_ours():
    def p(n, branch, created, cross=False):
        return {"number": n, "headRefName": branch, "createdAt": created,
                "labels": [{"name": "x"}], "url": f"u{n}", "isCrossRepository": cross}  # fmt: skip

    prs = automerge.updates([
        p(1, "update/b", "2026-11-02T10:00:00Z"),
        p(2, "update/a", "2026-11-01T10:00:00Z"),
        p(3, "feature/c", "2026-10-01T10:00:00Z"),
        p(4, "update/d", "2026-10-01T10:00:00Z", cross=True),
    ])  # fmt: skip
    assert [(x.number, x.labels) for x in prs] == [(2, ["x"]), (1, ["x"])]


def test_usage(capsys):
    assert automerge.main(["-n", "extra"]) == 2
    assert automerge.main(["--force"]) == 2
    assert "usage:" in capsys.readouterr().err
