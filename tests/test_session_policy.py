import unittest

from scripts.validate_session_policy import validate_policy


class SessionPolicyTests(unittest.TestCase):
    def test_session_policy_files_remain_aligned(self):
        result = validate_policy()
        self.assertEqual(result["failures"], [], "\n".join(result["failures"]))


if __name__ == "__main__":
    unittest.main()
