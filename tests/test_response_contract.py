import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


class ResponseContractTests(unittest.TestCase):
    def test_summarizer_role_requires_codex_style_output(self):
        content = (REPO_ROOT / "roles" / "summarizer-role.md").read_text()
        self.assertIn("Codex-style", content)
        self.assertIn("Lead with the outcome", content)
        self.assertIn("Do not tell the user to run commands manually", content)

    def test_runtime_prompt_requires_execution_oriented_language(self):
        content = (REPO_ROOT / "scripts" / "local_team_run.py").read_text()
        self.assertIn("Answer like a strong Codex-style coding assistant.", content)
        self.assertIn("visible progress", content)
        self.assertIn("takeover_message", content)

    def test_runtime_initializes_preflight_progress_before_heavy_bootstrap(self):
        content = (REPO_ROOT / "scripts" / "local_team_run.py").read_text()
        self.assertIn('"preflight"', content)
        self.assertIn('Bootstrapping runtime', content)
        self.assertIn('Assembling repo context', content)
        self.assertIn('Runtime ready', content)

    def test_live_status_mentions_elapsed_time_and_execution_mix(self):
        content = (REPO_ROOT / "scripts" / "team_status.py").read_text()
        self.assertIn("Working (", content)
        self.assertIn("EXECUTION", content)
        self.assertIn("cloud_session", content)
        self.assertIn('overall_status == "running"', content)


if __name__ == "__main__":
    unittest.main()
