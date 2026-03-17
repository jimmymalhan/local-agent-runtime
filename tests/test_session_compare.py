import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import session_compare
from scripts.session_compare import diff_excerpt


class SessionCompareTests(unittest.TestCase):
    def test_diff_excerpt_reports_identical_outputs(self):
        self.assertEqual(
            diff_excerpt("same output\n", "same output\n"),
            "No textual diff. Outputs matched exactly.",
        )

    def test_diff_excerpt_includes_unified_diff_headers(self):
        diff = diff_excerpt("alpha\n", "beta\n")
        self.assertIn("--- codex", diff)
        self.assertIn("+++ claude", diff)

    def test_active_run_lock_returns_live_lock_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_lock = Path(tmpdir) / "run.lock"
            run_lock.write_text(json.dumps({"pid": 123, "task": "demo", "target_repo": "/tmp/demo"}))
            with mock.patch.object(session_compare, "RUN_LOCK", run_lock), \
                 mock.patch.object(session_compare.os, "kill", return_value=None):
                body = session_compare.active_run_lock()

        self.assertEqual(body["pid"], 123)
        self.assertEqual(body["task"], "demo")

    def test_active_run_lock_ignores_stale_lock(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_lock = Path(tmpdir) / "run.lock"
            run_lock.write_text(json.dumps({"pid": 999, "task": "demo"}))
            with mock.patch.object(session_compare, "RUN_LOCK", run_lock), \
                 mock.patch.object(session_compare.os, "kill", side_effect=OSError):
                body = session_compare.active_run_lock()

        self.assertIsNone(body)


if __name__ == "__main__":
    unittest.main()
