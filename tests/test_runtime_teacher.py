import json
import pathlib
import tempfile
import unittest

from scripts import runtime_teacher


class RuntimeTeacherTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.lessons_path = pathlib.Path(self.tmpdir.name) / "runtime-lessons.json"
        self._orig = runtime_teacher.LESSONS_PATH
        runtime_teacher.LESSONS_PATH = self.lessons_path

    def tearDown(self):
        runtime_teacher.LESSONS_PATH = self._orig
        self.tmpdir.cleanup()

    def test_record_lesson_creates_entry(self):
        entry = runtime_teacher.record_lesson(
            category="resource",
            trigger="memory ceiling exceeded",
            lesson="System hit 84% memory during planner stage",
            fix="Downgrade planner model to 3b when memory > 70%",
        )
        self.assertEqual(entry["category"], "resource")
        lessons = runtime_teacher.load_lessons()
        self.assertEqual(len(lessons), 1)
        self.assertEqual(lessons[0]["trigger"], "memory ceiling exceeded")

    def test_record_lesson_deduplicates_by_trigger(self):
        runtime_teacher.record_lesson("resource", "mem high", "lesson 1", "fix 1")
        runtime_teacher.record_lesson("resource", "mem high", "lesson 2", "fix 2")
        lessons = runtime_teacher.load_lessons()
        self.assertEqual(len(lessons), 1)
        self.assertEqual(lessons[0]["lesson"], "lesson 2")

    def test_get_lessons_for_stage_filters_by_context(self):
        runtime_teacher.record_lesson("resource", "planner stall", "lesson", "fix", context="planner stage")
        runtime_teacher.record_lesson("quality", "generic output", "lesson", "fix", context="summarizer retry")
        planner_lessons = runtime_teacher.get_lessons_for_stage("planner")
        self.assertEqual(len(planner_lessons), 1)

    def test_get_lessons_for_category(self):
        runtime_teacher.record_lesson("resource", "t1", "l1", "f1")
        runtime_teacher.record_lesson("quality", "t2", "l2", "f2")
        runtime_teacher.record_lesson("resource", "t3", "l3", "f3")
        resource_lessons = runtime_teacher.get_lessons_for_category("resource")
        self.assertEqual(len(resource_lessons), 2)

    def test_mark_applied_increments_count(self):
        runtime_teacher.record_lesson("resource", "trigger1", "lesson", "fix")
        runtime_teacher.mark_applied("trigger1")
        runtime_teacher.mark_applied("trigger1")
        lessons = runtime_teacher.load_lessons()
        self.assertEqual(lessons[0]["applied_count"], 2)

    def test_format_lessons_for_prompt(self):
        runtime_teacher.record_lesson("resource", "t1", "Use lighter models under pressure", "Downgrade to 3b")
        lessons = runtime_teacher.load_lessons()
        prompt = runtime_teacher.format_lessons_for_prompt(lessons)
        self.assertIn("Runtime lessons", prompt)
        self.assertIn("Use lighter models", prompt)

    def test_report_shows_summary(self):
        runtime_teacher.record_lesson("resource", "t1", "lesson1", "fix1")
        runtime_teacher.record_lesson("quality", "t2", "lesson2", "fix2")
        report = runtime_teacher.report()
        self.assertIn("RUNTIME LESSONS", report)
        self.assertIn("resource", report)
        self.assertIn("quality", report)


if __name__ == "__main__":
    unittest.main()
