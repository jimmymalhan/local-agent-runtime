import datetime
import unittest
from unittest import mock

from scripts import team_status


class TeamStatusTests(unittest.TestCase):
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
