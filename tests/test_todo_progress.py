import tempfile
import textwrap
import unittest
from pathlib import Path

from scripts.todo_progress import parse_todo, render_report


class TodoProgressTests(unittest.TestCase):
    def test_parse_todo_computes_overall_and_section_percentages(self):
        body = textwrap.dedent(
            """\
            # TODO List

            ## Alpha
            - [x] done item
            - [ ] open item

            ## Beta
            - [x] finished
            - [x] finished too
            """
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "todo.md"
            path.write_text(body)
            parsed = parse_todo(path)

        self.assertEqual(parsed["overall"]["done"], 3)
        self.assertEqual(parsed["overall"]["open"], 1)
        self.assertEqual(parsed["overall"]["total"], 4)
        self.assertEqual(parsed["overall"]["percent"], 75.0)
        self.assertEqual(parsed["sections"][0]["name"], "Alpha")
        self.assertEqual(parsed["sections"][0]["percent"], 50.0)
        self.assertEqual(parsed["sections"][1]["name"], "Beta")
        self.assertEqual(parsed["sections"][1]["percent"], 100.0)

    def test_parse_todo_tracks_lane_breakdown(self):
        body = textwrap.dedent(
            """\
            # TODO List

            ## Runtime
            - [x] [local] migrate runtime state
            - [ ] [cloud] compare codex session output
            - [ ] common plan handoff cleanup

            ## General
            - [x] plain cleanup
            """
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "todo.md"
            path.write_text(body)
            parsed = parse_todo(path)

        self.assertEqual(parsed["lanes"]["local"]["done"], 1)
        self.assertEqual(parsed["lanes"]["cloud"]["open"], 1)
        self.assertEqual(parsed["lanes"]["shared"]["open"], 1)
        self.assertEqual(parsed["lanes"]["general"]["done"], 1)
        report = render_report(parsed)
        self.assertIn("Local agents", report)
        self.assertIn("Cloud/session takeover", report)

    def test_parse_todo_assigns_local_and_cloud_lanes(self):
        body = textwrap.dedent(
            """\
            # TODO List

            ## Runtime
            - [x] Improve local runtime progress view
            - [ ] Add Codex takeover fallback
            - [ ] General cleanup task
            """
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "todo.md"
            path.write_text(body)
            parsed = parse_todo(path)

        self.assertEqual(parsed["lanes"]["local"]["total"], 1)
        self.assertEqual(parsed["lanes"]["local"]["done"], 1)
        self.assertEqual(parsed["lanes"]["cloud"]["total"], 1)
        self.assertEqual(parsed["lanes"]["cloud"]["open"], 1)
        self.assertEqual(parsed["lanes"]["general"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
