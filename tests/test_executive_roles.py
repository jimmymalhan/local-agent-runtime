import pathlib
import unittest

from scripts import local_team_run, team_status


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


class ExecutiveRoleTests(unittest.TestCase):
    def test_executive_roles_have_prompt_focus(self):
        for role in ("manager", "director", "cto", "ceo"):
            self.assertIn(role, local_team_run.STAGE_FOCUS)
            self.assertTrue(local_team_run.STAGE_FOCUS[role])

    def test_executive_roles_have_role_files(self):
        for role in ("manager", "director", "cto", "ceo"):
            self.assertTrue(local_team_run.ROLE_FILES[role].exists())

    def test_team_status_describes_executive_roles(self):
        for role in ("manager", "director", "cto", "ceo"):
            text = team_status.role_description(role)
            self.assertNotEqual(text, "No role description.")
            self.assertNotEqual(text, "")


if __name__ == "__main__":
    unittest.main()
