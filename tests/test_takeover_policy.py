import pathlib
import tempfile
import unittest
from unittest import mock

from scripts import local_team_run


class TakeoverPolicyTests(unittest.TestCase):
    def test_takeover_message_includes_reason_and_command(self):
        target = pathlib.Path("/tmp/demo")
        message = local_team_run.takeover_message(target, "finish the task", "resource ceiling wait exceeded", "mem high")
        self.assertIn("resource ceiling wait exceeded", message)
        self.assertIn('codex "/tmp/demo" "finish the task"', message)
        self.assertIn("mem high", message)

    def test_record_runtime_lesson_appends_feedback_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_log = pathlib.Path(tmpdir) / "prompt-log.md"
            workflow_log = pathlib.Path(tmpdir) / "workflow-evolution.md"
            original_prompt = local_team_run.PROMPT_LOG_PATH
            original_workflow = local_team_run.WORKFLOW_EVOLUTION_PATH
            try:
                local_team_run.PROMPT_LOG_PATH = prompt_log
                local_team_run.WORKFLOW_EVOLUTION_PATH = workflow_log
                local_team_run.record_runtime_lesson(
                    "takeover",
                    "task text",
                    pathlib.Path("/tmp/demo"),
                    "run lock held too long",
                    "pid 123",
                )
            finally:
                local_team_run.PROMPT_LOG_PATH = original_prompt
                local_team_run.WORKFLOW_EVOLUTION_PATH = original_workflow

            self.assertIn("run lock held too long", prompt_log.read_text())
            self.assertIn("next-time:", workflow_log.read_text())

    def test_resource_wait_timeout_sets_takeover_state_and_targets_active_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = pathlib.Path(tmpdir)
            (temp_root / "state").mkdir(parents=True, exist_ok=True)
            (temp_root / "state" / "resource-status.json").write_text(
                '{"cpu_percent": 91.0, "memory_percent": 84.0}\n'
            )

            runtime = {
                "resource_limits": {
                    "cpu_percent": 70,
                    "memory_percent": 70,
                    "poll_seconds": 0,
                    "takeover_wait_seconds": 0,
                    "max_resource_wait_events": 1,
                }
            }
            target_repo = temp_root / "target"
            target_repo.mkdir()

            with mock.patch.object(local_team_run, "REPO_ROOT", temp_root), \
                 mock.patch.object(local_team_run, "run", return_value=mock.Mock(stdout="RESOURCE cpu=91.0%/70% mem=84.0%/70%")), \
                 mock.patch.object(local_team_run, "progress"), \
                 mock.patch.object(local_team_run, "record_runtime_lesson") as record_lesson, \
                 mock.patch.object(local_team_run, "set_takeover_state") as set_state, \
                 mock.patch.object(local_team_run, "current_stage_label", return_value="retriever"), \
                 mock.patch.object(local_team_run.time, "sleep"), \
                 mock.patch.dict(local_team_run.os.environ, {
                     "LOCAL_AGENT_ACTIVE_TASK": "finish the task",
                     "LOCAL_AGENT_TARGET_REPO": str(target_repo),
                 }, clear=False):
                with self.assertRaises(SystemExit) as ctx:
                    local_team_run.ensure_resource_capacity(runtime)

            set_state.assert_called_once_with(
                "finish the task",
                target_repo.resolve(),
                "resource ceiling wait budget exceeded",
                local_percent=0.0,
                cloud_percent=100.0,
            )
            record_lesson.assert_called_once()
            self.assertIn(str(target_repo.resolve()), str(record_lesson.call_args))
            self.assertIn("reduce parallelism", str(record_lesson.call_args))
            self.assertIn('codex "', str(ctx.exception))
            self.assertIn(str(target_repo.resolve()), str(ctx.exception))

    def test_resource_wait_budget_triggers_takeover_before_long_timeout(self):
        runtime = {
            "resource_limits": {
                "cpu_percent": 70,
                "memory_percent": 70,
                "poll_seconds": 0,
                "takeover_wait_seconds": 999,
                "max_resource_wait_events": 2,
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            target_repo = pathlib.Path(tmpdir) / "target"
            target_repo.mkdir()
            with mock.patch.object(local_team_run, "resource_status_snapshot", return_value=("RESOURCE cpu=25.0%/70% mem=84.0%/70%", {"cpu_percent": 25.0, "memory_percent": 84.0})), \
                 mock.patch.object(local_team_run, "progress"), \
                 mock.patch.object(local_team_run, "record_runtime_lesson") as record_lesson, \
                 mock.patch.object(local_team_run, "set_takeover_state") as set_state, \
                 mock.patch.object(local_team_run, "current_stage_label", return_value="retriever"), \
                 mock.patch.object(local_team_run.time, "sleep"), \
                 mock.patch.dict(local_team_run.os.environ, {
                     "LOCAL_AGENT_ACTIVE_TASK": "finish the task",
                     "LOCAL_AGENT_TARGET_REPO": str(target_repo),
                 }, clear=False):
                with self.assertRaises(SystemExit) as ctx:
                    local_team_run.ensure_resource_capacity(runtime)

        set_state.assert_called_once()
        self.assertIn("waited 2 times", str(record_lesson.call_args))
        self.assertIn("resource ceiling wait budget exceeded", str(ctx.exception))

    def test_parallel_work_downgrades_to_serial_when_headroom_is_tight(self):
        runtime = {
            "active_max_parallel_roles": 2,
            "resource_limits": {
                "cpu_percent": 70,
                "memory_percent": 70,
                "parallel_headroom_cpu_percent": 55,
                "parallel_headroom_memory_percent": 55,
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            target_repo = pathlib.Path(tmpdir) / "target"
            target_repo.mkdir()
            with mock.patch.object(local_team_run, "resource_status_snapshot", return_value=("RESOURCE cpu=22.0%/70% mem=84.0%/70%", {"cpu_percent": 22.0, "memory_percent": 84.0})), \
                 mock.patch.object(local_team_run, "record_runtime_lesson") as record_lesson, \
                 mock.patch.object(local_team_run, "progress"), \
                 mock.patch.dict(local_team_run.os.environ, {
                     "LOCAL_AGENT_ACTIVE_TASK": "finish the task",
                     "LOCAL_AGENT_TARGET_REPO": str(target_repo),
                 }, clear=False):
                result = local_team_run.effective_max_parallel_roles(runtime, ["researcher", "retriever"], {"qwen2.5:3b"})

        self.assertEqual(result, 1)
        record_lesson.assert_called_once()
        self.assertIn("parallel work reduced for headroom", str(record_lesson.call_args))

    def test_parallel_work_keeps_configured_width_when_headroom_is_healthy(self):
        runtime = {
            "active_max_parallel_roles": 2,
            "resource_limits": {
                "cpu_percent": 70,
                "memory_percent": 70,
                "parallel_headroom_cpu_percent": 55,
                "parallel_headroom_memory_percent": 55,
            },
        }
        with mock.patch.object(local_team_run, "resource_status_snapshot", return_value=("RESOURCE cpu=12.0%/70% mem=32.0%/70%", {"cpu_percent": 12.0, "memory_percent": 32.0})), \
             mock.patch.object(local_team_run, "record_runtime_lesson") as record_lesson:
            result = local_team_run.effective_max_parallel_roles(runtime, ["researcher", "retriever"], {"qwen2.5:3b"})

        self.assertEqual(result, 2)
        record_lesson.assert_not_called()


if __name__ == "__main__":
    unittest.main()
