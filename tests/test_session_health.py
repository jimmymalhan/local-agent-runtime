import unittest

from scripts.session_health import analyze_sessions
from scripts.session_health import parse_process_table


SAMPLE_PS = """
85578 84000 ttys018 T Mon Mar 16 20:14:10 2026 node /Users/jimmymalhan/.nvm/versions/node/v22.22.1/bin/codex --dangerously-bypass-approvals-and-sandbox
93146 84000 ttys018 S+ Mon Mar 16 20:17:18 2026 node /Users/jimmymalhan/.nvm/versions/node/v22.22.1/bin/codex --dangerously-bypass-approvals-and-sandbox
97879 38704 ttys022 S+ Mon Mar 16 20:19:09 2026 node /Users/jimmymalhan/.nvm/versions/node/v22.22.1/bin/codex --dangerously-bypass-approvals-and-sandbox
98111 38704 ttys022 S+ Mon Mar 16 20:20:09 2026 node /Users/jimmymalhan/.nvm/versions/node/v22.22.1/bin/codex --dangerously-bypass-approvals-and-sandbox
"""


class SessionHealthTests(unittest.TestCase):
    def test_parse_process_table_detects_codex_sessions(self):
        sessions = parse_process_table(SAMPLE_PS)
        self.assertEqual([item.pid for item in sessions], [85578, 93146, 97879, 98111])
        self.assertTrue(all(item.tool == "codex" for item in sessions))

    def test_analyze_sessions_flags_only_active_duplicates_on_same_tty(self):
        duplicates = analyze_sessions(parse_process_table(SAMPLE_PS))
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]["pid"], 97879)
        self.assertEqual(duplicates[0]["keep_pid"], 98111)
        self.assertEqual(duplicates[0]["tty"], "ttys022")


if __name__ == "__main__":
    unittest.main()
