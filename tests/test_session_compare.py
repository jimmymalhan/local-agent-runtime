import unittest

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


if __name__ == "__main__":
    unittest.main()
