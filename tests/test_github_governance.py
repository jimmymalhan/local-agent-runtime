import unittest
from unittest import mock

from scripts import github_governance


class GitHubGovernanceTests(unittest.TestCase):
    def test_protection_status_reports_private_plan_blocker(self):
        with mock.patch.object(
            github_governance,
            "repo_view",
            return_value={"nameWithOwner": "jimmymalhan/local-agent-runtime", "visibility": "PRIVATE"},
        ), mock.patch.object(
            github_governance,
            "branch_protection",
            side_effect=github_governance.GhError(
                "gh: Upgrade to GitHub Pro or make this repository public to enable this feature."
            ),
        ):
            status = github_governance.protection_status("jimmymalhan/local-agent-runtime", "main")

        self.assertEqual(status["status"], "blocked_by_plan")
        self.assertFalse(status["protected"])
        self.assertIn("Make the repo public or upgrade the plan", status["blocker"])

    def test_protection_status_reports_required_checks_when_protected(self):
        with mock.patch.object(
            github_governance,
            "repo_view",
            return_value={"nameWithOwner": "jimmymalhan/local-agent-runtime", "visibility": "PUBLIC"},
        ), mock.patch.object(
            github_governance,
            "branch_protection",
            return_value={"required_status_checks": {"contexts": ["Validate Runtime", "Lighthouse FC-007"]}},
        ):
            status = github_governance.protection_status("jimmymalhan/local-agent-runtime", "main")

        self.assertEqual(status["status"], "protected")
        self.assertTrue(status["protected"])
        self.assertEqual(status["required_checks"], ["Validate Runtime", "Lighthouse FC-007"])


if __name__ == "__main__":
    unittest.main()
