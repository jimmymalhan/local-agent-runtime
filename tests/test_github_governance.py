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
        self.assertEqual(status["protection_source"], "branch_protection")

    def test_protection_status_falls_back_to_rulesets_when_branch_protection_404s(self):
        rulesets = [
            {
                "id": 13995244,
                "name": "Protect main",
                "target": "branch",
                "enforcement": "active",
                "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
                "rules": [
                    {"type": "deletion"},
                    {"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "Validate Runtime"}]}},
                ],
            }
        ]
        with mock.patch.object(
            github_governance,
            "repo_view",
            return_value={"nameWithOwner": "jimmymalhan/local-agent-runtime", "visibility": "PUBLIC"},
        ), mock.patch.object(
            github_governance,
            "branch_protection",
            side_effect=github_governance.GhError("gh: Branch not protected (HTTP 404)"),
        ), mock.patch.object(
            github_governance,
            "repo_rulesets",
            return_value=[{"id": 13995244, "name": "Protect main", "target": "branch", "enforcement": "active"}],
        ), mock.patch.object(
            github_governance,
            "repo_ruleset",
            return_value=rulesets[0],
        ):
            status = github_governance.protection_status("jimmymalhan/local-agent-runtime", "main")

        self.assertEqual(status["status"], "protected")
        self.assertTrue(status["protected"])
        self.assertEqual(status["required_checks"], ["Validate Runtime"])
        self.assertEqual(status["protection_source"], "ruleset")

    def test_protection_status_reports_unprotected_when_no_matching_ruleset_exists(self):
        with mock.patch.object(
            github_governance,
            "repo_view",
            return_value={"nameWithOwner": "jimmymalhan/local-agent-runtime", "visibility": "PUBLIC"},
        ), mock.patch.object(
            github_governance,
            "branch_protection",
            side_effect=github_governance.GhError("gh: Branch not protected (HTTP 404)"),
        ), mock.patch.object(
            github_governance,
            "repo_rulesets",
            return_value=[],
        ):
            status = github_governance.protection_status("jimmymalhan/local-agent-runtime", "main")

        self.assertEqual(status["status"], "unprotected")
        self.assertFalse(status["protected"])
        self.assertIn("No active branch protection or matching repository ruleset", status["blocker"])


if __name__ == "__main__":
    unittest.main()
