import json
import pathlib
import unittest
from unittest import mock

from scripts import local_team_run


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


class RuntimeConfigTests(unittest.TestCase):
    def test_resource_wait_takeover_default_is_bounded(self):
        cfg = json.loads((REPO_ROOT / "config" / "runtime.json").read_text())
        self.assertEqual(cfg["resource_limits"]["takeover_wait_seconds"], 30)
        self.assertEqual(cfg["resource_limits"]["max_resource_wait_events"], 4)
        self.assertEqual(cfg["resource_limits"]["parallel_headroom_cpu_percent"], 70)
        self.assertEqual(cfg["resource_limits"]["parallel_headroom_memory_percent"], 70)
        self.assertEqual(cfg["lock_wait_seconds"], 15)
        self.assertEqual(cfg["resource_limits"]["model_downgrade_cpu_percent"], 60)
        self.assertEqual(cfg["resource_limits"]["model_downgrade_memory_percent"], 60)
        self.assertTrue(cfg["roi"]["kill_switch_enabled"])
        self.assertEqual(cfg["roi"]["negative_trend_window"], 6)
        self.assertEqual(cfg["roi"]["negative_trend_threshold"], 3)
        self.assertEqual(cfg["roi"]["max_event_age_minutes"], 15)

    def test_fast_profile_prefers_quick_action_over_waiting(self):
        cfg = json.loads((REPO_ROOT / "config" / "runtime.json").read_text())
        fast = cfg["profiles"]["fast"]
        self.assertEqual(fast["lock_wait_seconds"], 8)
        self.assertEqual(fast["resource_limits"]["takeover_wait_seconds"], 8)
        self.assertEqual(fast["resource_limits"]["max_resource_wait_events"], 3)
        self.assertEqual(fast["resource_limits"]["poll_seconds"], 1)
        self.assertEqual(fast["resource_limits"]["parallel_headroom_cpu_percent"], 65)
        self.assertEqual(fast["resource_limits"]["parallel_headroom_memory_percent"], 65)

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

    def test_provider_order_stays_local_only_without_external_enablement(self):
        cfg = json.loads((REPO_ROOT / "config" / "runtime.json").read_text())
        with mock.patch.dict(local_team_run.os.environ, {}, clear=False):
            order = local_team_run.provider_order_for_stage(cfg, "planner", {"cpu_percent": 10.0, "memory_percent": 10.0})
        self.assertEqual(order, ["ollama"])

    def test_reasoning_roles_can_prefer_github_models_when_enabled(self):
        cfg = json.loads((REPO_ROOT / "config" / "runtime.json").read_text())
        env = {
            "LOCAL_AGENT_ENABLE_GITHUB_MODELS": "1",
            "GITHUB_MODELS_TOKEN": "token",
        }
        with mock.patch.dict(local_team_run.os.environ, env, clear=False):
            order = local_team_run.provider_order_for_stage(cfg, "planner", {"cpu_percent": 10.0, "memory_percent": 10.0})
            provider, model = local_team_run.resolve_execution_target(cfg, "planner", ["deepseek-r1:8b"])
        self.assertEqual(order[0], "github_models")
        self.assertEqual(provider, "github_models")
        self.assertEqual(model, "openai/gpt-4.1")

    def test_high_pressure_can_route_to_clawbot_when_enabled(self):
        cfg = json.loads((REPO_ROOT / "config" / "runtime.json").read_text())
        env = {
            "LOCAL_AGENT_ENABLE_CLAWBOT": "1",
            "CLAWBOT_API_KEY": "token",
            "CLAWBOT_BASE_URL": "https://openclaw.ai/v1/chat/completions",
            "CLAWBOT_MODEL": "openclaw/fast",
        }
        with mock.patch.dict(local_team_run.os.environ, env, clear=False):
            order = local_team_run.provider_order_for_stage(cfg, "researcher", {"cpu_percent": 25.0, "memory_percent": 90.0})
            provider, model = local_team_run.resolve_execution_target(cfg, "researcher", ["qwen2.5:3b"], {"cpu_percent": 25.0, "memory_percent": 90.0})
        self.assertEqual(order[0], "clawbot")
        self.assertEqual(provider, "clawbot")
        self.assertEqual(model, "openclaw/fast")

    def test_openclaw_supports_fallback_token_and_model_envs(self):
        cfg = json.loads((REPO_ROOT / "config" / "runtime.json").read_text())
        env = {
            "LOCAL_AGENT_ENABLE_OPENCLAW": "1",
            "OPENCLAW_GATEWAY_PASSWORD": "token",
            "OPENCLAW_BASE_URL": "https://openclaw.ai",
            "OPENCLAW_REASONING_MODEL": "openclaw/reasoning",
        }
        with mock.patch.dict(local_team_run.os.environ, env, clear=False):
            order = local_team_run.provider_order_for_stage(cfg, "planner", {"cpu_percent": 30.0, "memory_percent": 92.0})
            provider, model = local_team_run.resolve_execution_target(cfg, "planner", ["deepseek-r1:8b"], {"cpu_percent": 30.0, "memory_percent": 92.0})
        self.assertIn("openclaw", order)
        self.assertEqual(provider, "openclaw")
        self.assertEqual(model, "openclaw/reasoning")


if __name__ == "__main__":
    unittest.main()
