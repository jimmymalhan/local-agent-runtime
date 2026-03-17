import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

from scripts import roi_guard


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


class RuntimeSafetyTests(unittest.TestCase):
    def test_roi_guard_trips_when_negative_runs_reach_threshold(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = pathlib.Path(tmpdir) / "roi-state.json"
            state_path.write_text(json.dumps({"events": [{"outcome": "negative"}, {"outcome": "negative"}], "kill_switch": True, "consecutive_negative": 2}))
            with mock.patch.object(roi_guard, "STATE_PATH", state_path):
                self.assertEqual(roi_guard.cmd_check(2), 2)

    def test_roi_guard_record_increments_negative_streak(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = pathlib.Path(tmpdir) / "roi-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "events": [{"outcome": "negative", "detail": "older"}],
                        "open": 10,
                        "percent": 50.0,
                        "avg_cost": 0.001,
                        "consecutive_negative": 1,
                    }
                )
            )
            with mock.patch.object(roi_guard, "STATE_PATH", state_path), \
                 mock.patch.object(roi_guard, "current_snapshot", return_value={"open": 10, "done": 5, "percent": 50.0, "avg_cost": 0.002}):
                self.assertEqual(roi_guard.cmd_record("failure", 2), 0)
                body = json.loads(state_path.read_text())
        self.assertEqual(body["consecutive_negative"], 2)
        self.assertTrue(body["kill_switch"])

    def test_restore_checkpoint_blocks_without_explicit_restore_approval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = pathlib.Path(tmpdir) / "project"
            target.mkdir()
            (target / "sample.txt").write_text("alpha\n")
            create = subprocess.run(
                ["bash", str(REPO_ROOT / "scripts" / "create_checkpoint.sh"), "unit-test", str(target)],
                capture_output=True,
                text=True,
                check=True,
            )
            checkpoint_path = pathlib.Path(create.stdout.strip().splitlines()[-1]).resolve()
            (target / "sample.txt").write_text("changed\n")

            restore = subprocess.run(
                ["bash", str(REPO_ROOT / "scripts" / "restore_checkpoint.sh"), str(checkpoint_path), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(restore.returncode, 2)
        self.assertIn("Destructive action blocked pending approval", restore.stderr)

    def test_destructive_gate_accepts_action_specific_approval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = pathlib.Path(tmpdir)
            proc = subprocess.run(
                ["bash", str(REPO_ROOT / "scripts" / "destructive_gate.sh"), "restore", str(target)],
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, "LOCAL_AGENT_APPROVE_ACTIONS": "restore,delete"},
            )

        self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
