import unittest
import os
import pathlib
import sys
import tempfile
import time
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import mock

from scripts import dashboard_server


class DashboardServerTests(unittest.TestCase):
    def test_teaching_state_filters_current_stage_and_counts_applications(self):
        progress = {"current_stage": "planner"}
        lessons = [
            {"category": "resource", "trigger": "planner stall", "context": "planner stage", "lesson": "Use lighter model", "fix": "Downgrade to 3b", "applied_count": 2},
            {"category": "quality", "trigger": "summarizer generic", "context": "summarizer retry", "lesson": "Tighten prompt", "fix": "Refine output", "applied_count": 1},
        ]

        teaching = dashboard_server._teaching_state(progress, lessons)

        self.assertEqual(teaching["current_stage"], "planner")
        self.assertEqual(teaching["total_lessons"], 2)
        self.assertEqual(teaching["applied_total"], 3)
        self.assertEqual(teaching["applicable_count"], 1)
        self.assertEqual(teaching["next_fix"], "Downgrade to 3b")

    def test_normalize_progress_marks_stale_incomplete_stages(self):
        progress = {
            "task": "Old task",
            "current_stage": "researcher",
            "overall": {"status": "idle", "percent": 7.3, "remaining_percent": 92.7},
            "stages": [
                {"id": "preflight", "label": "Preflight", "status": "completed", "percent": 100.0},
                {"id": "researcher", "label": "Researcher", "status": "pending", "percent": 1.0, "detail": ""},
            ],
        }

        normalized = dashboard_server._normalize_progress(progress, {}, {"type": "stale_progress"})

        self.assertEqual(normalized["overall"]["status"], "stale")
        self.assertEqual(normalized["current_stage"], "")
        self.assertEqual(normalized["stages"][0]["status"], "completed")
        self.assertEqual(normalized["stages"][1]["status"], "stale")

    def test_fallback_progress_synthesizes_live_running_state_when_snapshot_is_stale(self):
        progress = {
            "task": "old task",
            "overall": {"status": "completed", "percent": 100.0, "remaining_percent": 0.0},
            "stages": [],
        }
        todo = {"working": [{"text": "Fix backend tracker"}]}
        sessions = [{"type": "codex", "status": "active", "detail": "repo work"}]
        ui_updates = {"updating_count": 2}
        freshness = {"sources": [{"path": "state/progress.json", "stale": True}]}

        with mock.patch("scripts.dashboard_server.time.time", return_value=100.0):
            fallback = dashboard_server._fallback_progress(progress, todo, sessions, ui_updates, freshness, {})

        self.assertEqual(fallback["overall"]["status"], "running")
        self.assertEqual(fallback["task"], "Fix backend tracker")
        self.assertEqual(fallback["current_stage"], "implementer")
        self.assertEqual(fallback["stages"][0]["id"], "researcher")
        self.assertEqual(fallback["stages"][1]["id"], "planner")
        self.assertGreater(fallback["overall"]["percent"], 0.0)

    def test_load_todo_includes_sprint_stats_and_backlog_eta(self):
        fake_todo = {
            "overall": {"done": 2, "open": 3, "total": 5, "percent": 40.0},
            "sections": [
                {"name": "Active Work", "done": 1, "open": 2, "total": 3, "percent": 33.3, "items": []},
                {"name": "Current Focus", "done": 1, "open": 1, "total": 2, "percent": 50.0, "items": []},
            ],
            "lanes": {},
            "use_cases": {},
            "focus": {},
        }
        with mock.patch.object(dashboard_server, "parse_todo", return_value=fake_todo):
            todo = dashboard_server._load_todo()

        self.assertEqual(todo["stats"]["eta_minutes"], 9)
        self.assertEqual(todo["sprint_stats"]["open"], 3)
        self.assertEqual(todo["sprint_stats"]["eta_minutes"], 6)
        self.assertIn("Active Work", todo["sprint_stats"]["sections"])

    def test_completion_tracker_includes_eta_blockers_decisions_lessons_and_roi(self):
        todo = {
            "stats": {"total": 10, "done": 4, "open": 6, "percent": 40.0},
            "items": [
                {"text": "fix memory ceiling", "done": True},
                {"text": "ship dashboard tracker", "done": False},
            ],
            "blockers": [{"text": "memory ceiling still active"}],
        }
        progress = {
            "stages": [
                {"id": "researcher", "label": "Researcher", "status": "completed", "percent": 100.0},
                {"id": "implementer", "label": "Implementer", "status": "running", "percent": 50.0},
            ]
        }
        lessons = [{"category": "resource", "lesson": "Downgrade models earlier under memory pressure"}]
        blocker_resolution = {
            "type": "memory_ceiling",
            "options": [{"option": "Downgrade model", "eta_seconds": 5, "owner": "local", "detail": "Switch to qwen2.5:3b"}],
        }
        etas = {"pipeline_eta_display": "3m", "todo_eta_display": "18m"}
        roi = {"events": [{"outcome": "positive"}, {"outcome": "negative"}], "trend": "recovering"}

        completion = dashboard_server._completion_tracker(todo, progress, lessons, blocker_resolution, etas, roi)

        self.assertEqual(completion["overall_percent"], 45.0)
        self.assertEqual(completion["pipeline_eta"], "3m")
        self.assertEqual(completion["todo_eta"], "18m")
        self.assertEqual(completion["active_blockers"], 1)
        self.assertEqual(completion["resolved_blockers"], 1)
        self.assertEqual(completion["blocker_type"], "memory_ceiling")
        self.assertEqual(completion["roi_score"], 50)
        self.assertEqual(completion["roi_trend"], "recovering")
        self.assertGreaterEqual(completion["total_decisions"], 2)
        self.assertEqual(completion["lessons_count"], 1)
        self.assertEqual(len(completion["phases"]), 4)

    def test_completion_tracker_counts_in_flight_running_stage_progress(self):
        todo = {"stats": {"total": 10, "done": 4, "open": 6, "percent": 40.0}, "items": [], "blockers": []}
        progress = {"stages": [{"id": "backend-sync", "label": "Backend Sync", "status": "running", "percent": 50.0}]}
        completion = dashboard_server._completion_tracker(todo, progress, [], {"type": "default", "options": []}, {}, {})
        self.assertEqual(completion["overall_percent"], 45.0)

    def test_project_board_includes_lane_and_use_case_rollups(self):
        todo = {
            "lanes": {
                "local": {"done": 2, "open": 1, "total": 3, "percent": 66.7},
                "cloud": {"done": 1, "open": 2, "total": 3, "percent": 33.3},
            },
            "use_cases": {
                "product": {"done": 4, "open": 1, "total": 5, "percent": 80.0},
                "business": {"done": 1, "open": 1, "total": 2, "percent": 50.0},
            },
        }

        board = dashboard_server._project_board(todo)

        self.assertEqual(board["lanes"][0]["id"], "local")
        self.assertEqual(board["lanes"][1]["id"], "cloud")
        self.assertEqual(board["use_cases"][0]["id"], "product")
        self.assertEqual(board["use_cases"][1]["id"], "business")

    def test_jira_tracker_includes_goals_projects_tasks_and_checkpoints(self):
        todo = {
            "use_cases": {
                "product": {"done": 4, "open": 1, "total": 5, "percent": 80.0},
                "business": {"done": 1, "open": 1, "total": 2, "percent": 50.0},
            },
            "sections": [
                {"name": "Active Work", "done": 3, "open": 1, "total": 4, "percent": 75.0},
            ],
            "working": [{"text": "Ship tracker"}],
        }
        progress = {
            "task": "Ship tracker",
            "overall": {"percent": 45.0, "status": "running"},
            "stages": [
                {"id": "researcher", "status": "completed", "percent": 100.0},
                {"id": "planner", "status": "running", "percent": 35.0},
            ],
        }
        session = {"target_repo": "/tmp/does-not-exist", "task": "Ship tracker"}
        etas = {
            "todo_eta_display": "20m",
            "todo_eta_minutes": 20,
            "sprint_eta_display": "8m",
            "sprint_eta_minutes": 8,
            "pipeline_eta_display": "2m",
            "pipeline_eta_seconds": 120,
        }

        tracker = dashboard_server._jira_tracker(todo, progress, session, etas)

        self.assertEqual(tracker["goals"][0]["name"], "Product use cases")
        self.assertEqual(tracker["projects"][0]["name"], "Active Work")
        self.assertEqual(tracker["tasks"][0]["name"], "Ship tracker")
        self.assertIn("items", tracker["checkpoints"])
        self.assertEqual(tracker["overall_eta_display"], "8m")
        self.assertEqual(tracker["backlog_eta_display"], "20m")
        self.assertEqual(tracker["tasks"][0]["eta_display"], "2m")
        self.assertIn("eta_display", tracker["goals"][0])
        self.assertIn("eta_display", tracker["projects"][0])

    def test_ui_update_feed_marks_dirty_ui_files(self):
        fake_stat = SimpleNamespace(st_mtime=time.time(), st_mtime_ns=int(time.time() * 1_000_000_000), st_size=10)
        rels = [
            "scripts/dashboard_server.py",
            "scripts/live_dashboard.py",
            "scripts/start_local_cli.sh",
            "README.md",
            "tests/test_dashboard_server.py",
            "tests/test_live_dashboard.py",
        ]
        status_out = " M scripts/dashboard_server.py\n M scripts/live_dashboard.py\n"
        with mock.patch.object(dashboard_server.subprocess, "run", return_value=mock.Mock(stdout=status_out)), \
             mock.patch("pathlib.Path.stat", return_value=fake_stat):
            feed = dashboard_server._ui_update_feed()

        self.assertEqual(feed["updating_count"], 2)
        self.assertEqual(feed["items"][0]["status"], "updating")
        self.assertIn(feed["items"][0]["path"], rels)

    def test_session_board_assigns_local_current_task_and_blocker_options(self):
        progress = {"task": "Fix runtime blocker"}
        session = {}
        sessions = [{"type": "local-agent", "detail": "Fix runtime blocker", "status": "running"}]
        blocker_resolution = {
            "type": "memory_ceiling",
            "options": [
                {"option": "Downgrade model", "eta_seconds": 5, "detail": "Switch to qwen2.5:3b"},
                {"option": "Serialize local roles", "eta_seconds": 8, "detail": "Keep the run local"},
            ],
        }
        etas = {"pipeline_eta_display": "2m", "todo_eta_display": "30m"}
        todo = {"working": [{"text": "Do the next thing"}]}

        board = dashboard_server._session_board(progress, session, sessions, blocker_resolution, etas, todo)

        self.assertEqual(board[0]["id"], "local-agent")
        self.assertEqual(board[0]["assigned_work"], "Fix runtime blocker")
        self.assertEqual(board[1]["id"], "manager")
        self.assertEqual(board[1]["assigned_work"], "Downgrade model")
        self.assertEqual(board[2]["id"], "director")
        self.assertEqual(board[3]["id"], "cto")
        self.assertEqual(board[3]["assigned_work"], "Switch to qwen2.5:3b")
        self.assertEqual(board[5]["id"], "session-1")
        self.assertFalse(board[5]["active"])
        self.assertEqual(board[5]["status"], "standby")
        self.assertEqual(board[5]["assigned_work"], "Observed external session only. Local agents keep task ownership.")

    def test_author_name_prefers_git_config(self):
        with mock.patch.object(dashboard_server.subprocess, "run", return_value=mock.Mock(stdout="Jimmy Malhan\n")):
            self.assertEqual(dashboard_server._author_name(), "Jimmy Malhan")

    def test_detect_sessions_uses_author_label(self):
        ps_output = "user 123 0.0 0.0 ?? ?? S 00:00 node /usr/local/bin/codex\n"
        with mock.patch.object(dashboard_server, "_author_name", return_value="Jimmy Malhan"), mock.patch.object(
            dashboard_server.subprocess, "run", return_value=mock.Mock(stdout=ps_output)
        ), mock.patch.object(dashboard_server, "load_json", return_value={}):
            sessions = dashboard_server._detect_sessions()

        self.assertEqual(sessions[0]["label"], "Jimmy Malhan")
        self.assertEqual(sessions[0]["type"], "local-session")

    def test_runtime_config_exposes_provider_plan_and_groups(self):
        runtime_cfg = {
            "default_profile": "fast",
            "profiles": {
                "fast": {
                    "team_order": ["planner", "implementer"],
                    "group_order": [["planner"], ["implementer"]],
                }
            },
            "team": {
                "planner": {"model": "deepseek-r1:8b"},
                "implementer": {"model": "qwen2.5-coder:7b"},
            },
        }
        progress = {
            "stages": [
                {"id": "planner", "status": "completed", "percent": 100.0},
                {"id": "implementer", "status": "running", "percent": 35.0},
            ]
        }
        fake_runtime = SimpleNamespace(
            parse_selected_roles=lambda profile, runtime: ["planner", "implementer"],
            group_order_for=lambda roles, profile: [["planner"], ["implementer"]],
            provider_order_for_stage=lambda runtime, stage_id, resource: ["openclaw", "ollama"] if stage_id == "planner" else ["ollama"],
            provider_model_for_stage=lambda runtime, provider_name, stage_id: "openclaw/reasoning",
            provider_preference=lambda runtime: "openclaw",
            remote_fallback_allowed=lambda runtime: True,
        )
        with mock.patch.object(dashboard_server, "load_json", return_value=runtime_cfg), \
             mock.patch.dict(os.environ, {"LOCAL_AGENT_MODE": "fast"}, clear=False), \
             mock.patch.object(dashboard_server, "_live_resource_status", return_value={"cpu_percent": 10.0, "memory_percent": 20.0}), \
             mock.patch.dict(sys.modules, {"local_team_run": fake_runtime}):
            runtime = dashboard_server._runtime_config()
            groups = dashboard_server._runtime_groups(runtime, progress)

        self.assertEqual(runtime["provider_preference"], "openclaw")
        self.assertTrue(runtime["remote_fallback_allowed"])
        self.assertEqual(runtime["provider_plan"][0]["provider"], "openclaw")
        self.assertEqual(runtime["provider_plan"][1]["provider"], "ollama")
        self.assertEqual(groups[0]["provider_mix"], {"openclaw": 1})
        self.assertEqual(groups[1]["items"][0]["status"], "running")

    def test_collect_state_includes_openclaw_status(self):
        patches = [
            mock.patch.object(dashboard_server, "_openclaw_metrics", return_value={"configured": True, "base_url": "http://127.0.0.1:19000"}),
            mock.patch.object(dashboard_server, "_runtime_config", return_value={"team": {}, "provider_plan": [], "active_group_order": []}),
            mock.patch.object(dashboard_server, "_runtime_groups", return_value=[]),
            mock.patch.object(dashboard_server, "_detect_sessions", return_value=[]),
            mock.patch.object(dashboard_server, "_live_resource_status", return_value={"cpu_percent": 1.0, "memory_percent": 1.0}),
            mock.patch.object(dashboard_server, "_state_freshness", return_value={"sources": [], "stale_count": 0, "stale_sources": []}),
            mock.patch.object(dashboard_server, "_resolve_blockers", return_value={"type": "none", "options": []}),
            mock.patch.object(dashboard_server, "_load_lessons", return_value=[]),
            mock.patch.object(dashboard_server, "_ui_update_feed", return_value={"updating_count": 0, "items": []}),
            mock.patch.object(dashboard_server, "_compute_etas", return_value={}),
            mock.patch.object(dashboard_server, "_auto_remediate", return_value={}),
            mock.patch.object(dashboard_server, "_session_board", return_value=[]),
            mock.patch.object(dashboard_server, "_teaching_state", return_value={}),
            mock.patch.object(dashboard_server, "_history_timeline", return_value=[]),
            mock.patch.object(dashboard_server, "_task_flow", return_value={"nodes": []}),
            mock.patch.object(dashboard_server, "_project_board", return_value={"lanes": [], "use_cases": []}),
            mock.patch.object(dashboard_server, "_jira_tracker", return_value={"goals": [], "projects": [], "tasks": [], "checkpoints": {}}),
            mock.patch.object(dashboard_server, "_ops_summary", return_value=[]),
            mock.patch.object(dashboard_server, "_executive_negotiation", return_value=[]),
            mock.patch.object(dashboard_server, "_governance_status", return_value={}),
            mock.patch.object(dashboard_server, "_local_agent_activity", return_value=[]),
            mock.patch.object(dashboard_server, "_completion_tracker", return_value={}),
            mock.patch.object(dashboard_server, "load_json", return_value={}),
            mock.patch.object(dashboard_server, "_load_todo", return_value={"stats": {"total": 0, "done": 0, "open": 0, "percent": 0.0}, "working": []}),
        ]
        with ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            state = dashboard_server.collect_state()

        self.assertTrue(state["openclaw"]["configured"])
        self.assertEqual(state["openclaw"]["base_url"], "http://127.0.0.1:19000")

    def test_parse_usage_cost_extracts_total_and_tokens(self):
        parsed = dashboard_server._parse_usage_cost("Usage cost (30 days)\nTotal: $0.0000 · 0 tokens\n")
        self.assertEqual(parsed["total"], "$0.0000")
        self.assertEqual(parsed["tokens"], "0 tokens")

    def test_openclaw_metrics_collects_health_status_probe_and_usage(self):
        outputs = {
            ("gateway", "health"): "Gateway Health\nOK (0ms)\n",
            ("gateway", "status"): "Service: LaunchAgent (loaded)\nRuntime: running (pid 1, state active)\nListening: 127.0.0.1:19000\nRecommendation: run openclaw doctor\n",
            ("gateway", "probe"): "Gateway Status\nReachable: yes\nLocal loopback ws://127.0.0.1:19000\n  Connect: ok (13ms) · RPC: limited - missing scope: operator.read\n",
            ("gateway", "usage-cost"): "Usage cost (30 days)\nTotal: $0.0000 · 0 tokens\n",
        }

        def fake_run(*args):
            return outputs.get(tuple(args), "")

        with mock.patch.object(dashboard_server, "_run_openclaw", side_effect=fake_run), \
             mock.patch.object(dashboard_server, "openclaw_status", return_value={"configured": True, "base_url": "http://127.0.0.1:19000"}):
            metrics = dashboard_server._openclaw_metrics_uncached()

        self.assertTrue(metrics["health"]["ok"])
        self.assertTrue(metrics["service"]["loaded"])
        self.assertTrue(metrics["probe"]["reachable"])
        self.assertTrue(metrics["probe"]["limited"])
        self.assertEqual(metrics["usage_cost"]["total"], "$0.0000")

    def test_task_flow_uses_active_owner(self):
        flow = dashboard_server._task_flow(
            {"task": "Ship dashboard", "current_stage": "implementer"},
            {"type": "stale_progress"},
            {"stats": {"open": 12}},
            [
                {"label": "Local Agents", "active": True, "eta_display": "10m"},
                {"label": "Codex", "active": True, "eta_display": "30s"},
            ],
        )

        labels = [node["label"] for node in flow["nodes"]]
        self.assertIn("Todo open: 12", labels)
        self.assertIn("Stage: implementer", labels)
        self.assertIn("Owner: Local Agents", labels)
        self.assertIn("ETA: 10m", labels)

    def test_ops_summary_and_executive_negotiation(self):
        todo = {
            "stats": {"total": 10, "done": 4, "open": 6, "percent": 40.0},
            "blockers": [{"text": "fix blocker"}],
        }
        blocker_resolution = {"type": "memory_ceiling"}
        lessons = [{"category": "resource", "lesson": "Downgrade model earlier"}]
        etas = {"todo_eta_display": "18m", "sprint_eta_display": "6m"}
        board = [
            {"id": "manager", "active": True, "assigned_work": "Downgrade model"},
            {"id": "director", "active": True, "assigned_work": "Cut non-ROI work"},
            {"id": "cto", "active": True, "assigned_work": "Route reasoning remote"},
            {"id": "ceo", "active": True, "assigned_work": "Ship smallest slice"},
        ]

        summary = dashboard_server._ops_summary(todo, blocker_resolution, lessons, etas, board)
        negotiation = dashboard_server._executive_negotiation(board)

        self.assertEqual(summary[0]["id"], "complete")
        self.assertEqual(summary[0]["label"], "Active sprint")
        self.assertEqual(summary[1]["id"], "blockers")
        self.assertEqual(summary[-1]["id"], "roi")
        self.assertEqual(negotiation[0]["title"], "Manager vs Director")
        self.assertEqual(negotiation[1]["title"], "CTO vs CEO")
        self.assertGreaterEqual(negotiation[0]["tension"], 75)
        self.assertIn("wins this round", negotiation[0]["decision"])

    def test_ops_summary_and_completion_tracker_cover_roi_blockers_lessons(self):
        todo = {
            "stats": {"total": 10, "done": 4, "open": 6, "percent": 40.0},
            "blockers": [{"text": "Fix runtime stall"}],
            "items": [{"text": "Fix runtime stall", "done": True}],
        }
        blocker_resolution = {"type": "memory_ceiling", "options": [{"option": "Downgrade model", "eta_seconds": 5, "detail": "Use 3b"}]}
        lessons = [{"category": "resource", "lesson": "Prefer lighter model"}]
        etas = {"todo_eta_display": "20m", "sprint_eta_display": "6m", "pipeline_eta_display": "2m"}
        session_board = [{"active": True}, {"active": False}]
        roi = {"events": [], "trend": "healthy"}
        progress = {"stages": [{"id": "planner", "label": "Planner", "status": "completed"}]}

        ops = dashboard_server._ops_summary(todo, blocker_resolution, lessons, etas, session_board)
        completion = dashboard_server._completion_tracker(todo, progress, lessons, blocker_resolution, etas, roi)

        self.assertEqual(ops[0]["label"], "Active sprint")
        self.assertEqual(ops[-1]["label"], "Maximum ROI")
        self.assertEqual(completion["overall_percent"], 40.0)
        self.assertEqual(completion["blocker_type"], "memory_ceiling")
        self.assertEqual(completion["todo_eta"], "20m")
        self.assertEqual(completion["sprint_eta"], "6m")

    def test_governance_status_uses_recent_cache(self):
        cached = {
            "repo": "jimmymalhan/local-agent-runtime",
            "branch": "main",
            "status": "blocked_by_plan",
            "checked_at": "2099-03-16T23:50:00",
        }

        with mock.patch.object(dashboard_server, "load_json", return_value=cached):
            status = dashboard_server._governance_status(max_age_seconds=60)

        self.assertEqual(status["status"], "blocked_by_plan")

    def test_governance_status_refreshes_when_cache_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = pathlib.Path(tmpdir) / "governance-status.json"
            fake_module = SimpleNamespace(
                protection_status=lambda repo, branch: {
                    "repo": repo,
                    "branch": branch,
                    "visibility": "PRIVATE",
                    "protected": False,
                    "status": "blocked_by_plan",
                    "required_checks": [],
                    "blocker": "Plan gate",
                }
            )
            with mock.patch.object(dashboard_server, "load_json", return_value={}), mock.patch.object(
                dashboard_server, "_governance_cache_path", return_value=cache_path
            ), mock.patch.dict("sys.modules", {"github_governance": fake_module}):
                status = dashboard_server._governance_status(max_age_seconds=0)
                self.assertTrue(cache_path.exists())

        self.assertEqual(status["status"], "blocked_by_plan")

    def test_collect_state_cached_reuses_recent_snapshot(self):
        fake = {"server_time": "x"}
        with mock.patch.object(dashboard_server, "collect_state", return_value=fake) as collect:
            dashboard_server._STATE_CACHE["timestamp"] = 0.0
            dashboard_server._STATE_CACHE["data"] = None
            first = dashboard_server.collect_state_cached(max_age_seconds=60)
            second = dashboard_server.collect_state_cached(max_age_seconds=60)

        self.assertEqual(first, fake)
        self.assertEqual(second, fake)
        self.assertEqual(collect.call_count, 1)

    def test_ui_flags_disable_enhanced_panels_by_default(self):
        with mock.patch.object(dashboard_server, "_runtime_config", return_value={"ui": {"flags": {"enhanced_dashboard": False}}}):
            flags = dashboard_server._ui_flags()

        self.assertFalse(flags["enhanced_dashboard"])
        self.assertFalse(flags["executive_conflict"])
        self.assertFalse(flags["governance_panel"])
        self.assertFalse(flags["auto_remediation_panel"])

    def test_ui_flags_allow_env_override(self):
        runtime = {"ui": {"flags": {"enhanced_dashboard": False, "executive_conflict": False}}}
        with mock.patch.object(dashboard_server, "_runtime_config", return_value=runtime), mock.patch.dict(
            "os.environ",
            {
                "LOCAL_AGENT_UI_ENHANCED_DASHBOARD": "1",
                "LOCAL_AGENT_UI_EXECUTIVE_CONFLICT": "true",
            },
            clear=False,
        ):
            flags = dashboard_server._ui_flags()

        self.assertTrue(flags["enhanced_dashboard"])
        self.assertTrue(flags["executive_conflict"])

    def test_collect_state_cached_returns_stale_snapshot_while_refreshing(self):
        stale = {"server_time": "old"}
        dashboard_server._STATE_CACHE["timestamp"] = 1.0
        dashboard_server._STATE_CACHE["data"] = stale
        dashboard_server._STATE_CACHE["signature"] = (("state/progress.json", 1, 1),)
        dashboard_server._STATE_REFRESHING = False
        with mock.patch("scripts.dashboard_server.time.time", return_value=10.0), mock.patch.object(
            dashboard_server.threading, "Thread"
        ) as thread_cls:
            with mock.patch.object(
                dashboard_server, "_state_signature", return_value=(("state/progress.json", 1, 1),)
            ):
                result = dashboard_server.collect_state_cached(max_age_seconds=1.0)

        self.assertEqual(result, stale)
        thread_cls.assert_called_once()

    def test_collect_state_cached_refreshes_when_state_signature_changes(self):
        stale = {"server_time": "old"}
        fresh = {"server_time": "new"}
        dashboard_server._STATE_CACHE["timestamp"] = 50.0
        dashboard_server._STATE_CACHE["data"] = stale
        dashboard_server._STATE_CACHE["signature"] = (("state/progress.json", 1, 1),)
        dashboard_server._STATE_REFRESHING = False
        with mock.patch("scripts.dashboard_server.time.time", return_value=55.0), mock.patch.object(
            dashboard_server, "_state_signature", return_value=(("state/progress.json", 2, 1),)
        ), mock.patch.object(dashboard_server, "collect_state", return_value=fresh) as collect:
            result = dashboard_server.collect_state_cached(max_age_seconds=60.0)

        self.assertEqual(result, fresh)
        self.assertEqual(collect.call_count, 1)

    def test_state_freshness_reports_stale_sources(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            progress = pathlib.Path(tmpdir) / "progress.json"
            todo = pathlib.Path(tmpdir) / "todo.md"
            progress.write_text("{}")
            todo.write_text("# todo")
            stale_ts = time.time() - 120
            fresh_ts = time.time() - 2
            progress.touch()
            todo.touch()
            os.utime(progress, (stale_ts, stale_ts))
            os.utime(todo, (fresh_ts, fresh_ts))
            with mock.patch.object(dashboard_server, "_tracked_state_paths", return_value=[progress, todo]):
                freshness = dashboard_server._state_freshness()

        self.assertEqual(freshness["stale_count"], 1)
        self.assertEqual(freshness["stale_sources"][0]["path"], str(progress))


if __name__ == "__main__":
    unittest.main()
