import json
import pathlib
import tempfile
import unittest
from unittest import mock

from scripts import agent_coordinator


class AgentCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.state_dir = pathlib.Path(self.tmpdir.name)
        self.coord_path = self.state_dir / "agent-coordination.json"
        self.lock_path = self.state_dir / "agent-coordination.lock"
        self._orig_state_dir = agent_coordinator.STATE_DIR
        self._orig_coord = agent_coordinator.COORDINATION_PATH
        self._orig_lock = agent_coordinator.COORDINATION_LOCK
        agent_coordinator.STATE_DIR = self.state_dir
        agent_coordinator.COORDINATION_PATH = self.coord_path
        agent_coordinator.COORDINATION_LOCK = self.lock_path

    def tearDown(self):
        agent_coordinator.STATE_DIR = self._orig_state_dir
        agent_coordinator.COORDINATION_PATH = self._orig_coord
        agent_coordinator.COORDINATION_LOCK = self._orig_lock
        self.tmpdir.cleanup()

    def test_claim_files_succeeds_for_single_role(self):
        result = agent_coordinator.claim_files("researcher", ["src/main.py", "config/app.json"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["collisions"], [])

    def test_claim_files_detects_collision(self):
        agent_coordinator.claim_files("researcher", ["src/main.py"])
        result = agent_coordinator.claim_files("implementer", ["src/main.py"])
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["collisions"]), 1)
        self.assertEqual(result["collisions"][0]["file"], "src/main.py")
        self.assertEqual(result["collisions"][0]["claimed_by"], "researcher")

    def test_release_files_clears_claims(self):
        agent_coordinator.claim_files("researcher", ["src/main.py"])
        agent_coordinator.release_files("researcher")
        result = agent_coordinator.claim_files("implementer", ["src/main.py"])
        self.assertTrue(result["ok"])

    def test_current_claims_returns_active(self):
        agent_coordinator.claim_files("researcher", ["a.py"])
        agent_coordinator.claim_files("planner", ["b.py"])
        claims = agent_coordinator.current_claims()
        roles = [c["role"] for c in claims]
        self.assertIn("researcher", roles)
        self.assertIn("planner", roles)

    def test_stale_claims_are_pruned(self):
        from datetime import datetime, timedelta
        old_time = (datetime.now() - timedelta(seconds=200)).isoformat(timespec="seconds")
        state = {
            "claims": [{"role": "researcher", "files": ["x.py"], "pid": 1, "claimed_at": old_time}],
            "collisions": [],
            "updated_at": old_time,
        }
        self.coord_path.write_text(json.dumps(state))
        claims = agent_coordinator.current_claims()
        self.assertEqual(len(claims), 0)

    def test_status_report_includes_claims(self):
        agent_coordinator.claim_files("researcher", ["a.py"])
        report = agent_coordinator.status_report()
        self.assertIn("researcher", report)
        self.assertIn("a.py", report)


if __name__ == "__main__":
    unittest.main()
