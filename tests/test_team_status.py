import datetime
import unittest
from unittest import mock

from scripts import team_status


class TeamStatusTests(unittest.TestCase):
    def test_teaching_snapshot_counts_stage_lessons(self):
        progress = {"current_stage": "planner"}
        lessons = [
            {"category": "resource", "trigger": "planner stall", "context": "planner stage", "fix": "Downgrade", "applied_count": 2},
            {"category": "quality", "trigger": "generic", "context": "summarizer stage", "fix": "Refine", "applied_count": 1},
        ]
        with mock.patch.object(team_status, "load_lessons", return_value=lessons), \
             mock.patch.object(team_status, "get_lessons_for_stage", return_value=[lessons[0]]):
            snapshot = team_status.teaching_snapshot(progress)

        self.assertEqual(snapshot["applied_total"], 3)
        self.assertEqual(snapshot["top_fix"], "Downgrade")
        self.assertEqual(len(snapshot["stage_lessons"]), 1)

    def test_progress_is_stale_when_running_without_live_lock(self):
        stale_time = (datetime.datetime.now() - datetime.timedelta(seconds=30)).isoformat(timespec="seconds")
        progress = {
            "updated_at": stale_time,
            "overall": {"status": "running"},
        }
        with mock.patch.object(team_status, "lock_pid", return_value=0):
            self.assertTrue(team_status.progress_is_stale(progress))

    def test_progress_is_not_stale_when_live_lock_pid_exists(self):
        stale_time = (datetime.datetime.now() - datetime.timedelta(seconds=30)).isoformat(timespec="seconds")
        progress = {
            "updated_at": stale_time,
            "overall": {"status": "running"},
        }
        with mock.patch.object(team_status, "lock_pid", return_value=123), \
             mock.patch.object(team_status, "is_pid_alive", return_value=True):
            self.assertFalse(team_status.progress_is_stale(progress))


if __name__ == "__main__":
    unittest.main()
