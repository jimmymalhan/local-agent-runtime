import json
import pathlib
import tempfile
import unittest
from datetime import datetime, timedelta

from scripts import cloud_takeover_monitor


class CloudTakeoverTests(unittest.TestCase):
    def test_check_stall_detects_no_progress(self):
        stall_start = 100.0  # started stalling at t=100
        is_stalled, _ = cloud_takeover_monitor.check_stall(50.0, 50.0, stall_start, 30.0)
        # stall_start is 100, but check_stall uses time.time() internally
        # With stall_start=100, current time will be >> 130, so should be stalled
        self.assertTrue(is_stalled)

    def test_check_stall_resets_on_progress(self):
        is_stalled, new_start = cloud_takeover_monitor.check_stall(50.0, 55.0, 0, 30.0)
        self.assertFalse(is_stalled)
        self.assertGreater(new_start, 0)

    def test_check_total_timeout_fires(self):
        old = (datetime.now() - timedelta(seconds=700)).isoformat(timespec="seconds")
        self.assertTrue(cloud_takeover_monitor.check_total_timeout(old, 600))

    def test_check_total_timeout_not_yet(self):
        recent = datetime.now().isoformat(timespec="seconds")
        self.assertFalse(cloud_takeover_monitor.check_total_timeout(recent, 600))

    def test_check_total_timeout_empty_string(self):
        self.assertFalse(cloud_takeover_monitor.check_total_timeout("", 600))

    def test_write_takeover_creates_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "takeover-recommendation.json"
            orig = cloud_takeover_monitor.TAKEOVER_STATE_PATH
            cloud_takeover_monitor.TAKEOVER_STATE_PATH = path
            try:
                cloud_takeover_monitor.write_takeover("test reason", "test task", "/tmp/repo")
                self.assertTrue(path.exists())
                data = json.loads(path.read_text())
                self.assertEqual(data["reason"], "test reason")
                self.assertIn("codex", data["command"])
            finally:
                cloud_takeover_monitor.TAKEOVER_STATE_PATH = orig

    def test_check_roi_kill_switch_reads_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "roi-metrics.json"
            path.write_text(json.dumps({"kill_switch": True}))
            orig = cloud_takeover_monitor.ROI_STATE_PATH
            cloud_takeover_monitor.ROI_STATE_PATH = path
            try:
                self.assertTrue(cloud_takeover_monitor.check_roi_kill_switch())
            finally:
                cloud_takeover_monitor.ROI_STATE_PATH = orig

    def test_check_roi_kill_switch_false_when_healthy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "roi-metrics.json"
            path.write_text(json.dumps({"kill_switch": False}))
            orig = cloud_takeover_monitor.ROI_STATE_PATH
            cloud_takeover_monitor.ROI_STATE_PATH = path
            try:
                self.assertFalse(cloud_takeover_monitor.check_roi_kill_switch())
            finally:
                cloud_takeover_monitor.ROI_STATE_PATH = orig


if __name__ == "__main__":
    unittest.main()
