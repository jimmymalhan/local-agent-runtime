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


if __name__ == "__main__":
    unittest.main()
