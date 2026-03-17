import unittest
from scripts import blocker_resolver


class BlockerResolverTests(unittest.TestCase):
    def test_classify_memory_ceiling(self):
        ctx = {"resource": {"memory_percent": 90, "cpu_percent": 10}, "memory_limit": 85, "roi": {}}
        self.assertEqual(blocker_resolver.classify_blocker(ctx), "memory_ceiling")

    def test_classify_roi_kill_switch(self):
        ctx = {"resource": {"memory_percent": 50}, "roi": {"kill_switch": True}}
        self.assertEqual(blocker_resolver.classify_blocker(ctx), "roi_kill_switch")

    def test_classify_cpu_ceiling(self):
        ctx = {"resource": {"cpu_percent": 90, "memory_percent": 10}, "cpu_limit": 85, "roi": {}}
        self.assertEqual(blocker_resolver.classify_blocker(ctx), "cpu_ceiling")

    def test_classify_default(self):
        ctx = {"resource": {"cpu_percent": 10, "memory_percent": 10}, "roi": {}}
        self.assertEqual(blocker_resolver.classify_blocker(ctx), "default")

    def test_resolve_options_returns_2_3_options(self):
        for blocker_type in blocker_resolver.BLOCKER_STRATEGIES:
            options = blocker_resolver.resolve_options(blocker_type)
            self.assertGreaterEqual(len(options), 2)
            self.assertLessEqual(len(options), 3)

    def test_auto_resolve_picks_fastest(self):
        ctx = {"resource": {"memory_percent": 90}, "memory_limit": 85, "roi": {}}
        result = blocker_resolver.auto_resolve(ctx)
        self.assertEqual(result["blocker_type"], "memory_ceiling")
        self.assertEqual(result["chosen"]["speed"], 1)

    def test_execute_resolution_reset_roi(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as tmpdir:
            orig = blocker_resolver.REPO_ROOT
            blocker_resolver.REPO_ROOT = pathlib.Path(tmpdir)
            (pathlib.Path(tmpdir) / "state").mkdir()
            try:
                msg = blocker_resolver.execute_resolution("reset_roi", {})
                self.assertIn("reset", msg.lower())
            finally:
                blocker_resolver.REPO_ROOT = orig

    def test_report_includes_all_options(self):
        ctx = {"resource": {"cpu_percent": 10, "memory_percent": 10}, "roi": {}}
        text = blocker_resolver.report(ctx)
        self.assertIn("Option 1", text)
        self.assertIn("Option 2", text)
        self.assertIn("Auto-pick", text)

    def test_all_options_have_eta_seconds(self):
        for blocker_type, options in blocker_resolver.BLOCKER_STRATEGIES.items():
            for opt in options:
                self.assertIn("eta_seconds", opt, f"Missing eta_seconds in {blocker_type} option: {opt['option']}")
                self.assertGreater(opt["eta_seconds"], 0)

    def test_estimate_completion_with_stages(self):
        progress = {
            "stages": [
                {"id": "researcher", "status": "completed"},
                {"id": "planner", "status": "running"},
                {"id": "implementer", "status": "pending"},
                {"id": "summarizer", "status": "pending"},
            ]
        }
        todo_stats = {"total": 50, "done": 20, "open": 30}
        result = blocker_resolver.estimate_completion(progress, todo_stats)
        self.assertIn("pipeline_eta_seconds", result)
        self.assertIn("pipeline_eta_display", result)
        self.assertIn("todo_eta_display", result)
        self.assertGreater(result["pipeline_eta_seconds"], 0)
        self.assertEqual(result["remaining_roles"], 3)
        self.assertEqual(result["open_tasks"], 30)

    def test_estimate_completion_all_done(self):
        progress = {
            "stages": [
                {"id": "researcher", "status": "completed"},
                {"id": "summarizer", "status": "completed"},
            ]
        }
        todo_stats = {"total": 10, "done": 10, "open": 0}
        result = blocker_resolver.estimate_completion(progress, todo_stats)
        self.assertEqual(result["pipeline_eta_seconds"], 0)
        self.assertEqual(result["pipeline_eta_display"], "done")

    def test_fmt_eta_formatting(self):
        self.assertEqual(blocker_resolver._fmt_eta(0), "done")
        self.assertEqual(blocker_resolver._fmt_eta(30), "30s")
        self.assertEqual(blocker_resolver._fmt_eta(90), "1m 30s")
        self.assertEqual(blocker_resolver._fmt_eta(3600), "1h 0m")


if __name__ == "__main__":
    unittest.main()
