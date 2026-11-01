import io

import pytest

from kaetzli import report


class TestSparkline:
    def test_empty_series_is_a_dash(self):
        assert report.sparkline([]) == "—"

    def test_flat_series_sits_in_the_middle(self):
        assert report.sparkline([5, 5, 5]) == "▄▄▄"

    def test_scaled_to_the_series_own_range(self):
        assert report.sparkline([0, 7]) == "▁█"
        assert report.sparkline([10, 11, 12, 13, 14, 15, 16, 17]) == "▁▂▃▄▅▆▇█"

    def test_truncates_like_awk_int(self):
        # (3 - 0) * 7 / (10 - 0) = 2.1 -> index 3 (1-based) -> "▃"
        assert report.sparkline([0, 3, 10]) == "▁▃█"


class TestReport:
    def test_writes_stdout_and_the_job_summary(self, tmp_path):
        summary = tmp_path / "summary.md"
        summary.write_text("before\n")
        stdout = io.StringIO()
        r = report.Report(stdout=stdout, summary_path=summary)
        r.out("## title")
        r.out()
        assert stdout.getvalue() == "## title\n\n"
        assert summary.read_text() == "before\n## title\n\n"

    def test_without_a_job_summary_only_stdout(self):
        stdout = io.StringIO()
        r = report.Report(stdout=stdout, summary_path=None)
        r.out("x")
        assert stdout.getvalue() == "x\n"

    def test_from_environment(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "s"))
        assert report.Report.from_env().summary_path == tmp_path / "s"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", "")
        assert report.Report.from_env().summary_path is None

    def test_quiet_writes_nothing(self, tmp_path, capsys):
        r = report.Report.quiet()
        r.out("x")
        assert capsys.readouterr().out == ""


class TestNote:
    def test_a_note_is_italic(self):
        assert str(report.Note("no gh")) == "_no gh_"

    def test_run_prints_a_note_and_exits_zero(self, capsys):
        def main(argv):
            raise report.Note("nothing to do")

        assert report.run(main, []) == 0
        assert capsys.readouterr().out == "_nothing to do_\n"

    def test_run_sends_a_note_to_the_reports_destination(self, tmp_path):
        stdout = io.StringIO()
        r = report.Report(stdout=stdout, summary_path=tmp_path / "s")

        def main(argv):
            raise report.Note("x", report=r)

        assert report.run(main, []) == 0
        assert stdout.getvalue() == "_x_\n"
        assert (tmp_path / "s").read_text() == "_x_\n"

    def test_run_passes_the_exit_code_through(self):
        assert report.run(lambda argv: 3, []) == 3
        assert report.run(lambda argv: None, []) == 0


class TestTsv:
    def test_fields_are_escaped_like_jq(self):
        assert (
            report.tsv(["a\tb", "c\nd", "back\\slash", "cr\r"])
            == "a\\tb\tc\\nd\tback\\\\slash\tcr\\r"
        )

    @pytest.mark.parametrize(("value", "text"), [(None, ""), (False, ""), (0, "0"), ("", "")])
    def test_missing_values_are_empty(self, value, text):
        assert report.tsv([value]) == text
