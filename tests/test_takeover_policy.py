import pathlib
import tempfile
import unittest
from unittest import mock

from scripts import local_team_run


class TakeoverPolicyTests(unittest.TestCase):
    def test_extra_skill_text_includes_codereview_pilot_style_evidence_for_retriever(self):
        text = local_team_run.extra_skill_text_for("retriever", "diagnose the failure")
        self.assertIn("Evidence-proof skill for local agents", text)
        self.assertIn("collect proof, not opinions", text)

    def test_extra_skill_text_includes_counter_analysis_for_reviewer(self):
        text = local_team_run.extra_skill_text_for("reviewer", "review the change")
        self.assertIn("Counter-analysis skill for local agents", text)
        self.assertIn("materially different alternatives", text)

    def test_extra_skill_text_includes_change_safety_for_implementer(self):
        text = local_team_run.extra_skill_text_for("implementer", "implement the fix")
        self.assertIn("Change-safety skill for local agents", text)
        self.assertIn("smallest diff", text)

    def test_takeover_message_includes_reason_and_command(self):
        target = pathlib.Path("/tmp/demo")
        message = local_team_run.takeover_message(target, "finish the task", "resource ceiling wait exceeded", "mem high")
        self.assertIn("resource ceiling wait exceeded", message)
        self.assertIn('Local "/demo" "finish the task"', message)
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
                local_percent=100.0,
                cloud_percent=0.0,
            )
            record_lesson.assert_called_once()
            self.assertIn(str(target_repo.resolve()), str(record_lesson.call_args))
            self.assertIn("reduce parallelism", str(record_lesson.call_args))
            self.assertIn('Local "/target"', str(ctx.exception))
            self.assertIn("Recommended next local run", str(ctx.exception))

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

    def test_roi_kill_switch_blocks_next_stage_after_negative_trend(self):
        runtime = {
            "roi": {
                "kill_switch_enabled": True,
                "negative_trend_window": 4,
                "negative_trend_threshold": 2,
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = pathlib.Path(tmpdir) / "roi-metrics.json"
            original = local_team_run.ROI_STATE_PATH
            target_repo = pathlib.Path(tmpdir) / "target"
            target_repo.mkdir()
            state_path.write_text(
                '{"kill_switch": true, "trend": "negative", "events": [{"outcome": "negative"}, {"outcome": "negative"}]}\n'
            )
            try:
                local_team_run.ROI_STATE_PATH = state_path
                with mock.patch.object(local_team_run, "set_takeover_state") as set_state, \
                     mock.patch.object(local_team_run, "record_runtime_lesson") as record_lesson, \
                     mock.patch.dict(local_team_run.os.environ, {"LOCAL_AGENT_ACTIVE_TASK": "finish the task"}, clear=False):
                    with self.assertRaises(SystemExit) as ctx:
                        local_team_run.enforce_roi_kill_switch(runtime, "planner", target_repo)
            finally:
                local_team_run.ROI_STATE_PATH = original

        set_state.assert_called_once()
        record_lesson.assert_called_once()
        self.assertIn("roi kill switch triggered", str(ctx.exception))

    def test_remote_provider_skips_local_resource_wait(self):
        runtime = {
            "team": {
                "planner": {"label": "Planner"},
            },
            "active_retry_generic_output": 0,
            "roi": {
                "kill_switch_enabled": False,
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            target_repo = pathlib.Path(tmpdir) / "target"
            target_repo.mkdir()
            memory_dir = pathlib.Path(tmpdir) / "memory"
            memory_dir.mkdir()
            original_memory = local_team_run.MEMORY_DIR
            try:
                local_team_run.MEMORY_DIR = memory_dir
                with mock.patch.object(local_team_run, "load_resource_state", return_value={"cpu_percent": 20.0, "memory_percent": 90.0}), \
                     mock.patch.object(local_team_run, "resolve_execution_target", return_value=("github_models", "openai/gpt-4.1")), \
                     mock.patch.object(local_team_run, "ensure_resource_capacity") as ensure_capacity, \
                     mock.patch.object(local_team_run, "update_execution_state"), \
                     mock.patch.object(local_team_run, "build_stage_prompt", return_value="prompt"), \
                     mock.patch.object(local_team_run, "system_prompt_for", return_value="system"), \
                     mock.patch.object(local_team_run, "call_model", return_value="content"), \
                     mock.patch.object(local_team_run, "progress"), \
                     mock.patch.object(local_team_run, "record_roi_event"), \
                     mock.patch.object(local_team_run, "threading") as fake_threading:
                    fake_threading.Event.return_value = mock.Mock(wait=mock.Mock(return_value=True), set=mock.Mock())
                    fake_thread = mock.Mock(start=mock.Mock(), join=mock.Mock())
                    fake_threading.Thread.return_value = fake_thread
                    local_team_run.run_stage(runtime, "planner", target_repo, "task", {}, ["deepseek-r1:8b"], "stamp")
            finally:
                local_team_run.MEMORY_DIR = original_memory

        ensure_capacity.assert_not_called()


if __name__ == "__main__":
    unittest.main()
