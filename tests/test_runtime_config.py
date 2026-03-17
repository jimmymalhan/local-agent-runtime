import json
import pathlib
import unittest

from scripts import local_team_run


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


class RuntimeConfigTests(unittest.TestCase):
    def test_resource_wait_takeover_default_is_bounded(self):
        cfg = json.loads((REPO_ROOT / "config" / "runtime.json").read_text())
        self.assertEqual(cfg["resource_limits"]["takeover_wait_seconds"], 45)
        self.assertEqual(cfg["resource_limits"]["max_resource_wait_events"], 6)
        self.assertEqual(cfg["resource_limits"]["parallel_headroom_cpu_percent"], 55)
        self.assertEqual(cfg["resource_limits"]["parallel_headroom_memory_percent"], 55)
        self.assertEqual(cfg["lock_wait_seconds"], 15)
        self.assertEqual(cfg["resource_limits"]["model_downgrade_cpu_percent"], 50)
        self.assertEqual(cfg["resource_limits"]["model_downgrade_memory_percent"], 50)

    def test_fast_profile_prefers_quick_action_over_waiting(self):
        cfg = json.loads((REPO_ROOT / "config" / "runtime.json").read_text())
        fast = cfg["profiles"]["fast"]
        self.assertEqual(fast["lock_wait_seconds"], 8)
        self.assertEqual(fast["resource_limits"]["takeover_wait_seconds"], 4)
        self.assertEqual(fast["resource_limits"]["max_resource_wait_events"], 2)
        self.assertEqual(fast["resource_limits"]["poll_seconds"], 1)
        self.assertEqual(fast["resource_limits"]["parallel_headroom_cpu_percent"], 45)
        self.assertEqual(fast["resource_limits"]["parallel_headroom_memory_percent"], 45)

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

    def test_high_pressure_prefers_cheaper_models_before_waiting(self):
        cfg = json.loads((REPO_ROOT / "config" / "runtime.json").read_text())
        available = ["deepseek-r1:8b", "qwen2.5-coder:7b", "qwen2.5:3b", "llama3.2:3b", "gemma3:4b"]
        high_pressure = {"cpu_percent": 24.0, "memory_percent": 84.0}

        self.assertEqual(
            local_team_run.choose_model_for_stage(cfg, "retriever", available, high_pressure),
            "qwen2.5:3b",
        )
        self.assertEqual(
            local_team_run.choose_model_for_stage(cfg, "summarizer", available, high_pressure),
            "qwen2.5-coder:7b",
        )
        self.assertEqual(
            local_team_run.choose_model_for_stage(cfg, "qa", available, high_pressure),
            "qwen2.5-coder:7b",
        )


if __name__ == "__main__":
    unittest.main()
