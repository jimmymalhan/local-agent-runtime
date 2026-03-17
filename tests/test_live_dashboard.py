import unittest
from scripts import live_dashboard


class LiveDashboardTests(unittest.TestCase):
    def test_render_bar_returns_correct_width(self):
        bar = live_dashboard.render_bar(50.0, width=10, color="")
        self.assertIn("█" * 5, bar)
        self.assertIn("░" * 5, bar)

    def test_render_bar_clamps_to_bounds(self):
        bar_zero = live_dashboard.render_bar(-10.0, width=10, color="")
        bar_full = live_dashboard.render_bar(150.0, width=10, color="")
        self.assertIn("░" * 10, bar_zero)
        self.assertIn("█" * 10, bar_full)

    def test_elapsed_str_formats_correctly(self):
        from datetime import datetime, timedelta
        now = datetime.now()
        two_min_ago = (now - timedelta(minutes=2, seconds=41)).isoformat(timespec="seconds")
        result = live_dashboard.elapsed_str(two_min_ago)
        self.assertIn("2m", result)
        self.assertIn("41s", result)

    def test_elapsed_str_handles_none(self):
        self.assertEqual(live_dashboard.elapsed_str(None), "0s")

    def test_model_usage_breakdown_counts_providers(self):
        progress = {
            "stages": [
                {"id": "researcher", "status": "completed", "detail": "Completed with ollama:qwen2.5:3b"},
                {"id": "planner", "status": "running", "detail": "Running via github_models: openai/gpt-4.1"},
                {"id": "preflight", "status": "completed", "detail": ""},
            ]
        }
        runtime = {"team": {"researcher": {"model": "qwen2.5:3b"}, "planner": {"model": "deepseek-r1:8b"}}}
        breakdown = live_dashboard.model_usage_breakdown(progress, runtime)
        self.assertIn("ollama", breakdown)
        self.assertIn("github_models", breakdown)
        self.assertEqual(breakdown["ollama"]["completed"], 1)
        self.assertEqual(breakdown["github_models"]["running"], 1)

    def test_format_dashboard_returns_string_with_progress(self):
        progress = {
            "task": "test task",
            "started_at": "2026-03-16T10:00:00",
            "overall": {"percent": 45.0, "status": "running", "remaining_percent": 55.0},
            "stages": [
                {"id": "researcher", "label": "Researcher", "percent": 100.0, "status": "completed", "detail": "Done"},
                {"id": "planner", "label": "Planner", "percent": 30.0, "status": "running", "detail": "Working"},
            ],
        }
        runtime = {"team": {"researcher": {"model": "qwen2.5:3b"}, "planner": {"model": "deepseek-r1:8b"}}}
        session = {"execution": {"local_models": 100.0, "cloud_session": 0.0}}
        resource = {"cpu_percent": 35.0, "memory_percent": 55.0}
        lock = {"pid": 0}
        roi = {"kill_switch": False, "events": [{"outcome": "positive"}]}
        lessons = [{"category": "resource", "lesson": "Unload models earlier", "fix": "stop resident ollama"}]

        output = live_dashboard.format_dashboard(progress, runtime, session, resource, lock, roi, lessons)
        self.assertIn("45.0%", output)
        self.assertIn("test task", output)
        self.assertIn("PROGRESS", output)
        self.assertIn("LOCAL", output)
        self.assertIn("CLOUD", output)
        self.assertIn("NEXT DECISION", output)
        self.assertIn("EXECUTIVE NEGOTIATION", output)
        self.assertIn("Manager", output)
        self.assertIn("TEACHING LOOP", output)
        self.assertIn("ROI", output)

    def test_snapshot_returns_string(self):
        result = live_dashboard.snapshot()
        self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
