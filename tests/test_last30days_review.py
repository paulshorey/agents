"""Offline regressions for local adaptations to the pinned research skill."""

import contextlib
from datetime import datetime, timezone
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/last30days/scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("last30days_review", SCRIPTS / "last30days.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
import store
import watchlist
from lib import hosted
from lib.watchlist_schedule import parse_schedule, schedule_due


class HostedConstraintsTests(unittest.TestCase):
    def test_supported_hosted_request_keeps_depth_and_register(self):
        with patch.dict(engine.os.environ, {
            "LAST30DAYS_API_BASE": "https://hosted.invalid",
        }, clear=True), patch.object(engine.env, "get_config", return_value={}), \
                patch.object(engine.env, "read_secret_env", return_value="synthetic"), \
                patch.object(engine, "_law7_host_plan_gate", return_value=None), \
                patch.object(hosted, "run_hosted", return_value=0) as remote:
            parser = engine.build_parser()
            args = parser.parse_args(["best tools", "--quick", "--register", "dev", "--no-browser-cookies"])
            self.assertEqual(engine._main(parser, args, []), 0)
            remote.assert_called_once_with("best tools", "quick", emit="compact", save_dir=None, save_suffix="", register="dev")

    def test_unsupported_constraints_stop_before_hosted_or_local_search(self):
        flags = [
            ["--as-of", "2026-01-01"], ["--days", "7"],
            ["--lookback-days", "90"], ["--search", "reddit"],
            ["--plan", "{}"], ["--subreddits", "python"],
            ["--x-handle", "example"], ["--github-repo", "owner/repo"],
            ["--max-results", "5"], ["--emit", "html"],
        ]
        for flag in flags:
            with self.subTest(flag=flag), patch.dict(engine.os.environ, {
                "LAST30DAYS_API_BASE": "https://hosted.invalid",
            }, clear=True), patch.object(engine.env, "get_config", return_value={}), \
                    patch.object(engine.env, "read_secret_env", return_value="synthetic"), \
                    patch.object(engine, "_law7_host_plan_gate", return_value=None), \
                    patch.object(hosted, "run_hosted") as remote, \
                    patch.object(engine.pipeline, "run") as local, \
                    contextlib.redirect_stderr(io.StringIO()) as errors:
                parser = engine.build_parser()
                args = parser.parse_args(["best tools", "--no-browser-cookies", *flag])
                self.assertEqual(engine._main(parser, args, []), 2)
                remote.assert_not_called()
                local.assert_not_called()
                self.assertIn("Hosted API cannot honor", errors.getvalue())

    def test_supported_options_and_configured_source_filters(self):
        args = engine.build_parser().parse_args([
            "topic", "--quick", "--register", "dev", "--emit", "json",
            "--json-profile", "raw", "--save-dir", "/tmp/review",
            "--no-browser-cookies", "--days", "30",
        ])
        self.assertEqual(engine.hosted_unsupported_options(args, {}), [])
        self.assertEqual(engine.hosted_unsupported_options(args, {
            "LAST30DAYS_DEFAULT_SEARCH": "reddit", "EXCLUDE_SOURCES": "x",
        }), ["EXCLUDE_SOURCES", "LAST30DAYS_DEFAULT_SEARCH"])


class ScheduleTests(unittest.TestCase):
    def test_weekly_polling_and_duplicate_minute(self):
        topic = {"schedule": "0 8 * * 1", "last_run": "2026-10-12 08:00:01"}
        self.assertFalse(schedule_due(topic, datetime(2026, 10, 18, 8, tzinfo=timezone.utc)))
        monday = datetime(2026, 10, 19, 8, tzinfo=timezone.utc)
        self.assertTrue(schedule_due(topic, monday))
        topic["last_run"] = "2026-10-19 08:00:01"
        self.assertFalse(schedule_due(topic, monday.replace(second=50)))

    def test_daily_ranges_steps_lists_sunday_and_day_or_semantics(self):
        now = datetime(2026, 10, 18, 8, 15, tzinfo=timezone.utc)  # Sunday
        for schedule, expected in [
            ("*/15 8-10 * * 0,7", True), ("0 8 * * *", False),
            ("15 8 1 * 7", True), ("15 8 18 * 1", True),
            ("15 8 * 11 *", False), ("* * * * *", True),
        ]:
            with self.subTest(schedule=schedule):
                self.assertEqual(schedule_due({"schedule": schedule}, now), expected)

    def test_invalid_schedules_and_timestamps_fail_closed(self):
        for schedule in ["* * *", "60 8 * * *", "*/0 * * * *", "0 24 * * *", "0 8 * * MON"]:
            with self.subTest(schedule=schedule), self.assertRaises(ValueError):
                parse_schedule(schedule)
        with self.assertRaises(ValueError):
            schedule_due({"schedule": "* * * * *", "last_run": "broken"})

    def test_run_all_skips_non_due_and_invalid_topics(self):
        topics = [
            {"id": 1, "name": "weekly", "enabled": 1, "schedule": "0 8 * * 1"},
            {"id": 2, "name": "daily", "enabled": 1, "schedule": "0 8 * * *"},
            {"id": 3, "name": "invalid", "enabled": 1, "schedule": "broken"},
        ]
        now = datetime(2026, 10, 18, 8, tzinfo=timezone.utc)
        with patch.object(store, "list_topics", return_value=topics), \
                patch.object(store, "get_setting", return_value="5"), \
                patch.object(store, "get_daily_cost", return_value=0), \
                patch.object(store, "get_daily_unknown_cost_runs", return_value=0), \
                patch.object(watchlist, "datetime") as clock, \
                patch.object(watchlist, "schedule_due", wraps=schedule_due) as due, \
                patch.object(watchlist, "_run_topic", return_value={"status": "completed"}) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            clock.now.return_value = now
            watchlist.cmd_run_all(None)
            clock.now.assert_called_once_with(timezone.utc)
            self.assertTrue(all(call.args[1] == now for call in due.call_args_list))
        run.assert_called_once_with(topics[1])


class WatchlistPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.scope = store.scoped_db(Path(self.temp.name) / "research.db")
        self.scope.__enter__()
        self.addCleanup(self.scope.__exit__, None, None, None)
        self.topic = store.add_topic("fixture")

    def test_budget_validation_preserves_previous_setting(self):
        parser = watchlist.build_parser()
        for bad in ["5O", "-1", "nan", "inf", "-inf"]:
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                watchlist.cmd_config(parser.parse_args(["config", "budget", "--", bad]))
            self.assertEqual(store.get_setting("daily_budget"), "5.00")
        for good in ["0", "12.5"]:
            with contextlib.redirect_stdout(io.StringIO()):
                watchlist.cmd_config(parser.parse_args(["config", "budget", good]))
            self.assertEqual(float(store.get_setting("daily_budget")), float(good))

    def test_invalid_schedule_not_persisted(self):
        args = watchlist.build_parser().parse_args(["add", "invalid", "--schedule", "bad"])
        with self.assertRaises(SystemExit):
            watchlist.cmd_add(args)
        self.assertIsNone(store.get_topic("invalid"))

    def test_schema_and_storage_failures_leave_failed_run_with_costs(self):
        for fail_at in ["schema", "storage", "subprocess"]:
            with self.subTest(fail_at=fail_at):
                result = subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
                with patch.object(watchlist.subprocess, "run", return_value=result) as child, \
                        patch.object(watchlist.schema, "report_from_dict", return_value=object()) as convert, \
                        patch.object(store, "findings_from_report", return_value=[]) as findings, \
                        patch.object(store, "store_findings") as persist:
                    if fail_at == "schema":
                        convert.side_effect = ValueError("sensitive report content")
                    elif fail_at == "storage":
                        persist.side_effect = RuntimeError("sensitive storage content")
                    else:
                        child.side_effect = OSError("sensitive process content")
                    outcome = watchlist._run_topic(self.topic)
                self.assertEqual(outcome["status"], "failed")
                self.assertIn("token_cost", outcome)
                with store._connect() as conn:
                    row = conn.execute("SELECT status,error_message FROM research_runs ORDER BY id DESC LIMIT 1").fetchone()
                self.assertEqual(row["status"], "failed")
                self.assertNotIn("sensitive", row["error_message"])


if __name__ == "__main__":
    unittest.main()
