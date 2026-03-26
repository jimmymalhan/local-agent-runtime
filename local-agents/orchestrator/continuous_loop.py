#!/usr/bin/env python3
"""
continuous_loop.py — Never-stop task execution engine.

Runs forever processing the task queue. When empty, auto-generates new tasks
from project goals. Self-heals on failures. Scores every output.
The core mechanism for continuous improvement.

Usage:
    python3 -m orchestrator.continuous_loop --project <id>
    python3 -m orchestrator.continuous_loop --all      # all active projects
    python3 -m orchestrator.continuous_loop --forever  # never stop
"""
import os
import sys
import json
import time
import signal
import argparse
import logging
import psutil
from pathlib import Path
from datetime import datetime, date
from typing import Optional

BASE_DIR = str(Path(__file__).parent.parent)
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
SKILLS_DIR = os.path.join(BASE_DIR, "..", ".claude", "skills")
STOP_FILE = os.path.join(BASE_DIR, ".stop")
PATTERNS_LOG = os.path.join(REPORTS_DIR, "learned_patterns.jsonl")

sys.path.insert(0, BASE_DIR)
sys.path.insert(0, str(Path(__file__).parent))

Path(REPORTS_DIR).mkdir(exist_ok=True)

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("continuous_loop")

# ── optional imports (silent degradation) ─────────────────────────────────────
try:
    from agents import run_task as _run_task, route as _route
    _AGENTS = True
except ImportError:
    _AGENTS = False
    def _run_task(task):
        return {"status": "ok", "output": "", "quality": 0,
                "tokens_used": 0, "elapsed_s": 0.0, "agent_name": "stub"}
    def _route(task):
        return "executor"

try:
    from orchestrator.resource_guard import ResourceGuard
    _RESOURCE_GUARD = True
except ImportError:
    _RESOURCE_GUARD = False
    class ResourceGuard:  # noqa: F811
        def check(self):
            class S:
                ram_pct = 0.0
                cpu_pct = 0.0
                action = "normal"
            return S()

try:
    from dashboard.state_writer import update_agent, update_task_queue
    _DASHBOARD = True
except ImportError:
    _DASHBOARD = False
    def update_agent(*a, **kw): pass
    def update_task_queue(*a, **kw): pass

try:
    from tasks.task_suite import TASKS as _TASK_SUITE
    _TASK_SUITE_AVAILABLE = True
except ImportError:
    try:
        from tasks.task_suite_legacy import TASKS as _TASK_SUITE
        _TASK_SUITE_AVAILABLE = True
    except ImportError:
        _TASK_SUITE_AVAILABLE = False
        _TASK_SUITE = []

# ── task generation helpers ────────────────────────────────────────────────────

_AUTO_TASK_TEMPLATES = [
    {
        "category": "tdd",
        "title_tpl": "Add tests for {area}",
        "description_tpl": "Write unit tests for the {area} module, covering happy path, error cases, and edge cases.",
    },
    {
        "category": "doc",
        "title_tpl": "Document {area}",
        "description_tpl": "Write clear docstrings and inline comments for {area}. Include usage examples.",
    },
    {
        "category": "refactor",
        "title_tpl": "Refactor {area} for clarity",
        "description_tpl": "Refactor the {area} module: remove duplication, improve naming, apply SOLID principles.",
    },
    {
        "category": "review",
        "title_tpl": "Code review {area}",
        "description_tpl": "Review {area} for bugs, security issues, and performance bottlenecks. Suggest improvements.",
    },
    {
        "category": "scaffold",
        "title_tpl": "CI pipeline for {area}",
        "description_tpl": "Create a CI/CD workflow for {area}: lint, test, build steps in a GitHub Actions YAML.",
    },
]

_NEXT_AUTO_ID = 9000  # auto-generated tasks start above manually defined range


def _now_iso() -> str:
    return datetime.now().isoformat()


def _today_str() -> str:
    return date.today().strftime("%Y%m%d")


def _loop_log_path() -> str:
    return os.path.join(REPORTS_DIR, f"loop_{_today_str()}.jsonl")


def _session_log_path() -> str:
    return os.path.join(REPORTS_DIR, f"session_{_today_str()}.json")


def _append_jsonl(path: str, record: dict):
    """Append one JSON record to a .jsonl file, silent on error."""
    try:
        with open(path, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass


class ContinuousLoop:
    """Never-stop task execution engine.

    Processes the task queue forever.  When empty, auto-generates new tasks
    from project goals.  Self-heals on failures.  Scores every output.
    """

    def __init__(self, project_id: Optional[str] = None):
        self.project_id = project_id
        self.guard = ResourceGuard()

        # runtime counters
        self._iterations = 0
        self._tasks_today = 0
        self._quality_scores: list[float] = []
        self._consecutive_failures = 0
        self._claude_rescue_calls = 0
        self._total_tasks_seen = 0
        self._stopped = False
        self._current_task: Optional[dict] = None

        # backoff state
        self._backoff_s = 0.0

        # signal handlers for graceful exit
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        log.info("ContinuousLoop initialised (project=%s)", project_id or "all")

    # ── public entry point ────────────────────────────────────────────────────

    def run(self, project_id: Optional[str] = None, max_iterations: Optional[int] = None):
        """Main loop.  Runs until stop_conditions() returns True or max_iterations hit."""
        pid = project_id or self.project_id
        log.info("Starting continuous loop — project=%s max_iterations=%s", pid, max_iterations)

        while not self._stopped:
            self._iterations += 1
            if max_iterations and self._iterations > max_iterations:
                log.info("Reached max_iterations=%d — stopping cleanly.", max_iterations)
                break

            # ── 1. resource check ────────────────────────────────────────────
            status = self.guard.check()
            if status.action == "kill" or status.ram_pct > 90:
                log.warning("RAM %.1f%% — sleeping 10s for resource pressure", status.ram_pct)
                self._log_event("resource_pressure", {"ram_pct": status.ram_pct})
                time.sleep(10)
                continue

            # ── 2. stop conditions ───────────────────────────────────────────
            if self.stop_conditions():
                log.info("Stop condition met — exiting loop.")
                break

            # ── 3. get next task ─────────────────────────────────────────────
            task = self.get_next_task(pid)

            # ── 4. auto-generate if queue empty ──────────────────────────────
            if task is None:
                generated = self.auto_generate_tasks(pid)
                if not generated:
                    log.info("Queue empty and no tasks generated — sleeping 30s.")
                    time.sleep(30)
                    continue
                task = self.get_next_task(pid)
                if task is None:
                    time.sleep(5)
                    continue

            # ── 5. mark in_progress ──────────────────────────────────────────
            self._current_task = task
            task["status"] = "in_progress"
            task.setdefault("attempts", 0)
            self._update_dashboard_in_progress(task)

            # ── 6. execute with retry ─────────────────────────────────────────
            result = self._execute_with_retry(task)
            score = float(result.get("quality", 0))

            # ── 7. record outcome ─────────────────────────────────────────────
            self._quality_scores.append(score)
            self._tasks_today += 1
            self._total_tasks_seen += 1

            if score >= 60:
                self._consecutive_failures = 0
                self._backoff_s = 0.0
                self._complete_task(task, result)

                # ── 8. promote patterns for high scores ──────────────────────
                if score >= 90:
                    self.promote_pattern(task, result)
            else:
                self._consecutive_failures += 1
                self._backoff_s = min(self._backoff_s * 2 + 5, 60)
                self._fail_task(task, result)
                log.warning(
                    "Task '%s' scored %.0f < 60 after all retries — backoff %.0fs",
                    task.get("title", "?"), score, self._backoff_s,
                )

            # ── 9. loop log ───────────────────────────────────────────────────
            self._log_event("task_done", {
                "task_id": task.get("id"),
                "title": task.get("title"),
                "score": score,
                "agent": result.get("agent_name"),
                "elapsed_s": result.get("elapsed_s", 0),
                "iteration": self._iterations,
            })

            # ── 10. dashboard heartbeat ───────────────────────────────────────
            self._update_dashboard_summary()

            # ── 11. backoff if needed ─────────────────────────────────────────
            if self._backoff_s > 0:
                time.sleep(self._backoff_s)

        # loop ended
        self._current_task = None
        self._write_session_summary()
        log.info(
            "Loop finished — iterations=%d tasks=%d quality_avg=%.1f",
            self._iterations, self._tasks_today, self._quality_avg(),
        )

    # ── task retrieval ────────────────────────────────────────────────────────

    def get_next_task(self, project_id: Optional[str] = None) -> Optional[dict]:
        """Return the next pending task from the queue, or None if empty."""
        # Try ProjectManager first (future integration point)
        task = self._get_from_project_manager(project_id)
        if task:
            return task

        # Fall back to todo.md
        task = self._get_from_todo_md()
        if task:
            return task

        # Fall back to built-in task suite
        if _TASK_SUITE_AVAILABLE and _TASK_SUITE:
            for t in _TASK_SUITE:
                if t.get("status") in (None, "pending", "todo"):
                    return dict(t)

        return None

    def _get_from_project_manager(self, project_id: Optional[str]) -> Optional[dict]:
        """Attempt to pull a task from local-agents/projects/<id>/tasks.json."""
        if not project_id:
            return None
        tasks_file = os.path.join(BASE_DIR, "projects", project_id, "tasks.json")
        if not os.path.exists(tasks_file):
            return None
        try:
            with open(tasks_file) as f:
                tasks = json.load(f)
            for t in tasks:
                if t.get("status") in (None, "pending", "todo"):
                    return dict(t)
        except Exception as e:
            log.debug("ProjectManager load error: %s", e)
        return None

    def _get_from_todo_md(self) -> Optional[dict]:
        """Parse local-agents/tasks/todo.md (simple markdown checklist)."""
        todo_path = os.path.join(BASE_DIR, "tasks", "todo.md")
        if not os.path.exists(todo_path):
            return None
        try:
            global _NEXT_AUTO_ID
            with open(todo_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("- [ ]"):
                        title = line[5:].strip()
                        _NEXT_AUTO_ID += 1
                        return {
                            "id": _NEXT_AUTO_ID,
                            "title": title,
                            "description": title,
                            "category": "code_gen",
                            "status": "pending",
                            "source": "todo.md",
                        }
        except Exception as e:
            log.debug("todo.md parse error: %s", e)
        return None

    # ── auto-generation ───────────────────────────────────────────────────────

    def auto_generate_tasks(self, project_id: Optional[str] = None) -> list[dict]:
        """Generate 3-5 new tasks when the queue is empty.

        Reads project description + completed tasks, then infers what is missing
        (tests, docs, CI, etc.) and appends new tasks.
        """
        global _NEXT_AUTO_ID
        log.info("Queue empty — auto-generating tasks for project=%s", project_id or "default")

        # Collect context about what has been done
        completed_titles: list[str] = []
        area = project_id or "local-agents"

        project_dir = os.path.join(BASE_DIR, "projects", project_id) if project_id else None
        if project_dir and os.path.exists(project_dir):
            tasks_file = os.path.join(project_dir, "tasks.json")
            if os.path.exists(tasks_file):
                try:
                    with open(tasks_file) as f:
                        for t in json.load(f):
                            if t.get("status") == "done":
                                completed_titles.append(t.get("title", ""))
                except Exception:
                    pass

        # Determine coverage gaps
        has_tests = any("test" in t.lower() for t in completed_titles)
        has_docs  = any("doc" in t.lower() for t in completed_titles)
        has_ci    = any("ci" in t.lower() or "pipeline" in t.lower() for t in completed_titles)
        has_review = any("review" in t.lower() for t in completed_titles)

        priorities = []
        if not has_tests:
            priorities.append("tdd")
        if not has_docs:
            priorities.append("doc")
        if not has_ci:
            priorities.append("scaffold")
        if not has_review:
            priorities.append("review")
        # Always include a refactor to keep quality high
        priorities.append("refactor")

        # Generate up to 5 tasks
        new_tasks: list[dict] = []
        for tpl in _AUTO_TASK_TEMPLATES:
            if tpl["category"] not in priorities:
                continue
            _NEXT_AUTO_ID += 1
            task = {
                "id": _NEXT_AUTO_ID,
                "title": tpl["title_tpl"].format(area=area),
                "description": tpl["description_tpl"].format(area=area),
                "category": tpl["category"],
                "status": "pending",
                "source": "auto_generated",
                "generated_at": _now_iso(),
            }
            new_tasks.append(task)
            if len(new_tasks) >= 5:
                break

        # Persist to project if we have one
        if new_tasks and project_dir:
            tasks_file = os.path.join(project_dir, "tasks.json")
            try:
                existing: list[dict] = []
                if os.path.exists(tasks_file):
                    with open(tasks_file) as f:
                        existing = json.load(f)
                existing.extend(new_tasks)
                with open(tasks_file, "w") as f:
                    json.dump(existing, f, indent=2)
            except Exception as e:
                log.warning("Could not persist auto-generated tasks: %s", e)

        log.info("Auto-generated %d tasks for project=%s", len(new_tasks), area)
        self._log_event("auto_generated_tasks", {
            "project": area,
            "count": len(new_tasks),
            "titles": [t["title"] for t in new_tasks],
        })
        return new_tasks

    # ── execution ─────────────────────────────────────────────────────────────

    def _execute_with_retry(self, task: dict) -> dict:
        """Run the task with up to 3 different approaches on low scores."""
        # attempt 1 — original task
        result = self._execute_task(task)
        if result.get("quality", 0) >= 60:
            return result

        log.info("Attempt 1 scored %.0f — retrying with subtask decomposition", result.get("quality", 0))
        task["_prev_result_1"] = result

        # attempt 2 — break into subtasks
        result2 = self.retry_with_different_approach(task, result)
        if result2.get("quality", 0) >= 60:
            return result2

        log.info("Attempt 2 scored %.0f — retrying with codebase context", result2.get("quality", 0))
        task["_prev_result_2"] = result2

        # attempt 3 — add codebase context, retry
        result3 = self.retry_with_different_approach(task, result2)
        # Return whichever was best
        best = max([result, result2, result3], key=lambda r: r.get("quality", 0))
        return best

    def _execute_task(self, task: dict) -> dict:
        """Single execution attempt via agents router."""
        task["attempts"] = task.get("attempts", 0) + 1
        t0 = time.time()
        try:
            result = _run_task(task)
        except Exception as e:
            result = {
                "status": "error",
                "output": str(e),
                "quality": 0,
                "tokens_used": 0,
                "elapsed_s": time.time() - t0,
                "agent_name": _route(task),
                "error": str(e),
            }
            log.error("Agent raised exception on task '%s': %s", task.get("title"), e)
        return result

    def retry_with_different_approach(self, task: dict, prev_result: dict) -> dict:
        """Smart retry: each call uses the next strategy.

        Strategy progression:
          - No _prev_result_1 key → attempt 1 already done; decompose into subtasks.
          - Has _prev_result_1   → attempt 2; add codebase context.
        """
        attempt = task.get("attempts", 1)

        if attempt == 1:
            # Strategy 2: decompose into smaller subtasks, run each, combine
            return self._retry_decomposed(task, prev_result)
        else:
            # Strategy 3: add codebase context
            return self._retry_with_context(task, prev_result)

    def _retry_decomposed(self, task: dict, prev_result: dict) -> dict:
        """Split task into 2-3 smaller subtasks; run each; return best."""
        log.info("Retry strategy: decompose subtasks for '%s'", task.get("title"))
        subtasks = [
            dict(task, title=f"{task.get('title')} — Part 1: structure", category=task.get("category", "code_gen")),
            dict(task, title=f"{task.get('title')} — Part 2: logic",     category=task.get("category", "code_gen")),
        ]
        results = []
        for st in subtasks:
            st["attempts"] = 0  # fresh count for subtask
            r = self._execute_task(st)
            results.append(r)

        # Combine: best quality, merged output
        best = max(results, key=lambda r: r.get("quality", 0))
        combined_output = "\n\n---\n\n".join(r.get("output", "") for r in results)
        best = dict(best, output=combined_output)
        # Average quality is fairer for combined subtask work
        avg_q = sum(r.get("quality", 0) for r in results) / len(results)
        best["quality"] = round(avg_q, 1)
        return best

    def _retry_with_context(self, task: dict, prev_result: dict) -> dict:
        """Enrich task description with codebase context then retry."""
        log.info("Retry strategy: add codebase context for '%s'", task.get("title"))
        enriched = dict(task)
        enriched["description"] = (
            f"{task.get('description', '')}\n\n"
            f"[Context from previous attempt]\n"
            f"Previous output (score {prev_result.get('quality', 0):.0f}/100):\n"
            f"{str(prev_result.get('output', ''))[:500]}\n\n"
            f"Please improve on this. Focus on correctness and completeness."
        )
        enriched["codebase_path"] = BASE_DIR
        enriched["attempts"] = 0
        result = self._execute_task(enriched)
        # Track which approach worked
        result["retry_strategy"] = "codebase_context"
        return result

    # ── pattern promotion ─────────────────────────────────────────────────────

    def promote_pattern(self, task: dict, result: dict):
        """When a task scores >=90, extract and save the approach that worked."""
        pattern = {
            "ts": _now_iso(),
            "task_title": task.get("title"),
            "task_category": task.get("category"),
            "score": result.get("quality"),
            "agent": result.get("agent_name"),
            "retry_strategy": result.get("retry_strategy", "first_attempt"),
            "approach_notes": (
                f"Category={task.get('category')} routed to agent={result.get('agent_name')} "
                f"scored {result.get('quality')}/100 on attempt {task.get('attempts', 1)}"
            ),
            "output_snippet": str(result.get("output", ""))[:300],
        }

        # Log to learned_patterns.jsonl
        _append_jsonl(PATTERNS_LOG, pattern)

        # Append to relevant .claude/skills/ file
        skills_dir = Path(SKILLS_DIR)
        if skills_dir.exists():
            category = task.get("category", "general")
            skill_file = skills_dir / f"{category}.md"
            section = (
                f"\n\n## Pattern That Works (auto-learned {_now_iso()[:10]})\n"
                f"**Task:** {task.get('title')}\n"
                f"**Score:** {result.get('quality')}/100\n"
                f"**Agent:** {result.get('agent_name')}\n"
                f"**Strategy:** {pattern['retry_strategy']}\n"
                f"**Notes:** {pattern['approach_notes']}\n"
            )
            try:
                with open(skill_file, "a") as f:
                    f.write(section)
                log.info("Promoted pattern to %s", skill_file)
            except Exception as e:
                log.debug("Could not write pattern to skill file: %s", e)
        else:
            log.debug("Skills dir not found at %s — pattern saved to %s only", SKILLS_DIR, PATTERNS_LOG)

    # ── stop conditions ───────────────────────────────────────────────────────

    def stop_conditions(self) -> bool:
        """Return True if the loop should stop."""
        # Manual kill switch
        if os.path.exists(STOP_FILE):
            log.info("Stop file detected at %s — halting.", STOP_FILE)
            return True

        # 5+ consecutive failures
        if self._consecutive_failures >= 5:
            log.error("5 consecutive failures — stopping to prevent runaway errors.")
            return True

        # System RAM > 90%
        try:
            ram_pct = psutil.virtual_memory().percent
            if ram_pct > 90:
                log.warning("RAM %.1f%% > 90%% — stopping for system health.", ram_pct)
                return True
        except Exception:
            pass

        # Claude rescue budget > 10% of total tasks
        if self._total_tasks_seen > 0:
            rescue_pct = self._claude_rescue_calls / self._total_tasks_seen * 100
            if rescue_pct > 10:
                log.warning(
                    "Claude rescue budget %.1f%% > 10%% — stopping to stay local-first.", rescue_pct
                )
                return True

        return False

    # ── task completion helpers ───────────────────────────────────────────────

    def _complete_task(self, task: dict, result: dict):
        """Mark task done and update all tracking structures."""
        task["status"] = "done"
        task["completed_at"] = _now_iso()
        task["final_score"] = result.get("quality", 0)
        self._persist_task_status(task)
        update_agent(
            task.get("_agent", result.get("agent_name", "executor")),
            status="idle",
            task="",
        )
        update_task_queue(completed_delta=1, in_progress_delta=-1)
        log.info(
            "DONE  task='%s' score=%.0f agent=%s",
            task.get("title"), result.get("quality", 0), result.get("agent_name"),
        )

    def _fail_task(self, task: dict, result: dict):
        """Mark task failed after all retries exhausted."""
        task["status"] = "failed"
        task["failed_at"] = _now_iso()
        task["final_score"] = result.get("quality", 0)
        self._persist_task_status(task)
        update_agent(
            task.get("_agent", result.get("agent_name", "executor")),
            status="idle",
            task="",
        )
        update_task_queue(failed_delta=1, in_progress_delta=-1)
        log.warning(
            "FAIL  task='%s' score=%.0f agent=%s",
            task.get("title"), result.get("quality", 0), result.get("agent_name"),
        )

    def _persist_task_status(self, task: dict):
        """Write updated task status back to its source file if available."""
        project_id = task.get("project_id") or self.project_id
        if not project_id:
            return
        tasks_file = os.path.join(BASE_DIR, "projects", project_id, "tasks.json")
        if not os.path.exists(tasks_file):
            return
        try:
            with open(tasks_file) as f:
                tasks = json.load(f)
            for t in tasks:
                if t.get("id") == task.get("id"):
                    t.update(task)
                    break
            with open(tasks_file, "w") as f:
                json.dump(tasks, f, indent=2)
        except Exception as e:
            log.debug("Could not persist task status: %s", e)

    # ── dashboard updates ─────────────────────────────────────────────────────

    def _update_dashboard_in_progress(self, task: dict):
        """Mark task in_progress on the dashboard."""
        agent_name = _route(task)
        task["_agent"] = agent_name
        update_agent(agent_name, status="running", task=task.get("title", ""), task_id=task.get("id"))
        update_task_queue(in_progress_delta=1, pending_delta=-1)

    def _update_dashboard_summary(self):
        """Write loop summary into state.json via state_writer."""
        if not _DASHBOARD:
            return
        try:
            from dashboard.state_writer import _read, _write
            state = _read()
            state.setdefault("continuous_loop", {})
            state["continuous_loop"] = {
                "current_task": self._current_task.get("title") if self._current_task else None,
                "tasks_completed_today": self._tasks_today,
                "quality_avg": round(self._quality_avg(), 1),
                "consecutive_failures": self._consecutive_failures,
                "iterations": self._iterations,
                "last_activity": _now_iso(),
            }
            _write(state)
        except Exception as e:
            log.debug("Dashboard summary update failed: %s", e)

    # ── session logging ───────────────────────────────────────────────────────

    def _log_event(self, event_type: str, data: dict):
        record = {"ts": _now_iso(), "event": event_type, **data}
        _append_jsonl(_loop_log_path(), record)

    def _write_session_summary(self):
        summary = {
            "ts": _now_iso(),
            "project_id": self.project_id,
            "iterations": self._iterations,
            "tasks_completed": self._tasks_today,
            "quality_avg": round(self._quality_avg(), 1),
            "consecutive_failures_at_end": self._consecutive_failures,
            "claude_rescue_calls": self._claude_rescue_calls,
            "total_tasks_seen": self._total_tasks_seen,
        }
        try:
            with open(_session_log_path(), "w") as f:
                json.dump(summary, f, indent=2)
            log.info("Session summary written to %s", _session_log_path())
        except Exception as e:
            log.debug("Could not write session summary: %s", e)

    # ── signal handling ───────────────────────────────────────────────────────

    def _handle_signal(self, signum, frame):
        sig_name = "SIGINT" if signum == 2 else "SIGTERM"
        log.info("%s received — will exit after current task completes.", sig_name)
        self._stopped = True

    # ── helpers ───────────────────────────────────────────────────────────────

    def _quality_avg(self) -> float:
        return sum(self._quality_scores) / len(self._quality_scores) if self._quality_scores else 0.0


# ── CLI entry point ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="continuous_loop — never-stop task execution engine",
    )
    parser.add_argument("--project", help="Run loop for a specific project ID")
    parser.add_argument("--all", action="store_true", help="Run loop across all active projects")
    parser.add_argument("--forever", action="store_true", help="Never stop (no iteration cap)")
    parser.add_argument("--max-iterations", type=int, default=None,
                        help="Stop after N iterations (default: unlimited)")
    args = parser.parse_args()

    loop = ContinuousLoop(project_id=args.project)
    max_iters = None if args.forever else args.max_iterations

    if args.all:
        # Discover all project directories
        projects_dir = os.path.join(BASE_DIR, "projects")
        project_ids = []
        if os.path.exists(projects_dir):
            project_ids = [
                d for d in os.listdir(projects_dir)
                if os.path.isdir(os.path.join(projects_dir, d))
            ]
        if not project_ids:
            log.info("No project directories found — running in default mode.")
            loop.run(max_iterations=max_iters)
        else:
            for pid in project_ids:
                if loop._stopped:
                    break
                log.info("=== Project: %s ===", pid)
                sub = ContinuousLoop(project_id=pid)
                sub.run(project_id=pid, max_iterations=max_iters)
    else:
        loop.run(project_id=args.project, max_iterations=max_iters)


if __name__ == "__main__":
    main()
