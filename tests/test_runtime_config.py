import json
import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


class RuntimeConfigTests(unittest.TestCase):
    def test_roi_model_assignment_uses_heavy_reasoning_only_on_high_leverage_roles(self):
        cfg = json.loads((REPO_ROOT / "config" / "runtime.json").read_text())
        team = cfg["team"]

        cheap_roles = {"researcher", "retriever", "optimizer", "user_acceptance"}
        coder_roles = {"architect", "implementer", "tester", "debugger"}
        reasoning_roles = {"planner", "reviewer", "benchmarker", "qa", "summarizer"}

        for role in cheap_roles:
            self.assertEqual(team[role]["model"], "qwen2.5:3b")
        for role in coder_roles:
            self.assertEqual(team[role]["model"], "qwen2.5-coder:7b")
        for role in reasoning_roles:
            self.assertEqual(team[role]["model"], "deepseek-r1:8b")


if __name__ == "__main__":
    unittest.main()
