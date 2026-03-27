#!/usr/bin/env python3
"""
orchestrator/main.py — Self-running v1→v1000 upgrade loop
==========================================================
Fully autonomous. No human input required.

Flow per version:
  1. Check hardware resources (pause if RAM >80%)
  2. Route each task to the right specialized agent
  3. Run Opus 4.6 on same task for baseline comparison
  4. Log comparison to reports/v{N}_compare.jsonl
  5. Update agent registry with scores
  6. Every 5 versions: run frustration research + apply patches
  7. After all tasks: gap analysis via benchmarker.py
  8. If gap > 5pts in any category: trigger upgrade_agent.py
  9. Stop when local beats Opus 4.6 across ALL categories OR at v100

Claude guardrail: 3-point check before ANY rescue call
  1. Task blocked 3+ times?
  2. Rescue budget < 10%?
  3. Category is rescue-eligible?

Usage:
  python3 orchestrator/main.py --version 1 --quick 3    # run 3 tasks
  python3 orchestrator/main.py --auto 1                 # full loop v1→v100
  python3 orchestrator/main.py --version 4 --local-only # skip Opus comparison
"""
import os, sys, json, time, argparse, subprocess, threading
from pathlib import Path
from datetime import datetime

BASE_DIR    = str(Path(__file__).parent.parent)
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
REGISTRY    = os.path.join(BASE_DIR, "registry", "agents.json")
BENCHMARKS  = os.path.join(BASE_DIR, "benchmarks")
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

Path(REPORTS_DIR).mkdir(exist_ok=True)

from orchestrator.resource_guard import ResourceGuard
from agents.benchmarker import analyze_version

# Schema validation — normalize task status and agent outputs (P0 root cause fixes)
try:
    from orchestrator.schema_validator import normalize_task_status, update_task_status
    _SCHEMA_VALIDATOR = True
except ImportError:
    _SCHEMA_VALIDATOR = False

# Token enforcer — enforce rescue budget limits (TASK-FIX-5)
try:
    from orchestrator.token_enforcer import is_rescue_allowed, deduct_tokens, get_status as get_token_status
    _TOKEN_ENFORCER = True
except ImportError:
    _TOKEN_ENFORCER = False
    def is_rescue_allowed(task_id):
        return True  # Fallback: allow rescue if enforcer unavailable
    def deduct_tokens(tokens):
        return True

# Schema validator fallback (if import failed above)
if not _SCHEMA_VALIDATOR:
    def normalize_task_status(status):
        if status in ["completed", "done", "is_done", True]:
            return "completed"
        elif status in ["in_progress", "running"]:
            return "in_progress"
        elif status in ["pending", "queued"]:
            return "pending"
        elif status in ["failed", "error"]:
            return "failed"
        else:
            return "pending"
    def update_task_status(task, status):
        task["status"] = normalize_task_status(status)
        if normalize_task_status(status) == "completed":
            task["is_done"] = True
        return task

# Supervisor — runs pre-flight + background health monitoring
try:
    from orchestrator.supervisor import get_supervisor as _get_sv
    _SUPERVISOR_AVAILABLE = True
except ImportError:
    _SUPERVISOR_AVAILABLE = False
    def _get_sv(): return None

# Auto-upgrade — self-improving prompt engine
try:
    from orchestrator.auto_upgrade import run_auto_upgrade as _auto_upgrade
    _AUTO_UPGRADE = True
except ImportError:
    _AUTO_UPGRADE = False
    def _auto_upgrade(*a, **kw): return []

# Auto-heal — always-on component health monitor
try:
    from orchestrator.auto_heal import get_auto_heal as _get_auto_heal
    _AUTO_HEAL = True
except ImportError:
    _AUTO_HEAL = False
    class _FakeAutoHeal:
        def start(self): pass
        def check_all(self): return {"healthy": True, "issues": []}
    def _get_auto_heal(): return _FakeAutoHeal()

# Checkpoint manager — 30s agent checkpoints + version rollback
try:
    from orchestrator.checkpoint_manager import get_cm as _get_cm
    _CHECKPOINT = True
except ImportError:
    _CHECKPOINT = False
    class _FakeCM:
        def snapshot_version(self, *a, **kw): pass
        def has_regressed(self, *a, **kw): return False
        def rollback_version(self, *a, **kw): return False
        def checkpoint_agent(self, *a, **kw): pass
    def _get_cm(): return _FakeCM()

# Error pattern library — auto-fix known errors <3s
try:
    from error_patterns import get_library as _get_error_lib, auto_fix as _auto_fix
    _ERROR_PATTERNS = True
except ImportError:
    _ERROR_PATTERNS = False
    def _get_error_lib(): return None
    def _auto_fix(error, agent="", context=None): return None

# Self-calibration — 3-task warmup per version before production pool
try:
    from orchestrator.calibration import calibrate_all_agents as _calibrate, get_passing_agents
    _CALIBRATION = True
except ImportError:
    _CALIBRATION = False
    def _calibrate(version, agents): return {}
    def get_passing_agents(results): return set()

# Self-improving prompt engine — A/B test prompts, auto-improve
try:
    from orchestrator.prompt_engine import get_prompt_engine as _get_pe
    _PROMPT_ENGINE = True
except ImportError:
    _PROMPT_ENGINE = False
    class _FakePE:
        def record_task(self, *a, **kw): return False
        def record_ab_result(self, *a, **kw): pass
        def stats(self): return {}
    def _get_pe(): return _FakePE()

# Dashboard state writer — non-blocking; failures are silent to not break the loop
try:
    from dashboard.state_writer import (
        update_agent, update_version, update_task_queue,
        update_token_usage, update_hardware, log_failure,
        log_research, update_benchmark_score, update_version_changelog,
    )
    _DASHBOARD = True
except ImportError:
    _DASHBOARD = False
    def update_agent(*a, **kw): pass
    def update_version(*a, **kw): pass
    def update_task_queue(*a, **kw): pass
    def update_token_usage(*a, **kw): pass
    def update_hardware(*a, **kw): pass
    def log_failure(*a, **kw): pass
    def log_research(*a, **kw): pass
    def update_benchmark_score(*a, **kw): pass
    def update_version_changelog(*a, **kw): pass

# Board init — pre-populate dashboard with ALL tasks before any agent moves
try:
    from dashboard.board_init import init_board as _init_board, update_task_status as _update_task_status
    _BOARD_INIT = True
except ImportError:
    _BOARD_INIT = False
    def _init_board(*a, **kw): pass
    def _update_task_status(*a, **kw): pass

# Autonomous execution — full self-governance without Claude
try:
    from orchestrator.autonomous_executor import AutonomousExecutor
    _AUTONOMOUS_EXECUTOR = True
except ImportError:
    _AUTONOMOUS_EXECUTOR = False
    class _FakeAE:
        def execute_task(self, *a, **kw): return None
    def _get_executor(): return _FakeAE()

# Adaptive budgeting — auto-adjust per success rates
try:
    from registry.adaptive_budgeting import AdaptiveBudgeting
    _ADAPTIVE_BUDGETING = True
except ImportError:
    _ADAPTIVE_BUDGETING = False
    class _FakeAB:
        def check_and_adjust(self): return {}
    def _get_budgeting(): return _FakeAB()

# ── Claude guardrail config ────────────────────────────────────────────────
CLAUDE_RESCUE_BUDGET  = 0.10   # max 10% of tasks rescued by Claude
RESCUE_BLOCK_COUNT    = 3      # task must fail 3+ times before Claude rescue
RESCUE_INELIGIBLE_CATS = {"research", "doc", "documentation"}  # local handles these
CLAUDE_TOKEN_CAP      = 200    # hard cap per rescue call

# ── 1-minute rescue watchdog ──────────────────────────────────────────────
_WATCHDOG_INTERVAL   = 60      # check every 60 seconds
_AGENT_STUCK_AFTER   = 120     # agent stuck if running >120s without state change
_watchdog_stop       = threading.Event()
_watchdog_rescued    = {}      # task_id → last rescue ts to prevent double-rescue

def _rescue_watchdog(state_path: str, version_ref: list, rescued_ref: list,
                     total_tasks: int):
    """
    Background thread: every 60s check state.json for stuck agents.
    If an agent has been 'running' for >AGENT_STUCK_AFTER seconds without
    progress → record for Claude rescue on next task cycle.
    """
    while not _watchdog_stop.wait(_WATCHDOG_INTERVAL):
        try:
            if not os.path.exists(state_path):
                continue
            with open(state_path) as f:
                state = json.load(f)
            now = time.time()
            agents = state.get("agents", {})
            for name, info in agents.items():
                if info.get("status") != "running":
                    continue
                task_id = info.get("task_id")
                if task_id is None:
                    continue
                # Check last update time
                last_update_iso = info.get("last_update", "")
                if not last_update_iso:
                    continue
                try:
                    last_ts = datetime.fromisoformat(last_update_iso).timestamp()
                except Exception:
                    continue
                stuck_secs = now - last_ts
                if stuck_secs > _AGENT_STUCK_AFTER:
                    # Only alert once per task_id per 5 minutes
                    last_rescued = _watchdog_rescued.get(task_id, 0)
                    if now - last_rescued > 300:
                        _watchdog_rescued[task_id] = now
                        msg = (f"[WATCHDOG] Agent '{name}' stuck {int(stuck_secs)}s "
                               f"on task {task_id} — flagging for rescue")
                        print(msg)
                        update_agent("benchmarker", "upgrading",
                                     f"[WATCHDOG] {name} stuck {int(stuck_secs)}s", task_id)
                        # Log to reports for main loop to pick up
                        watchdog_log = os.path.join(REPORTS_DIR, "watchdog_rescues.jsonl")
                        rec = {"ts": datetime.now().isoformat(), "agent": name,
                               "task_id": task_id, "stuck_secs": int(stuck_secs),
                               "version": version_ref[0]}
                        with open(watchdog_log, "a") as wf:
                            wf.write(json.dumps(rec) + "\n")
        except Exception:
            pass  # watchdog never crashes the main loop


def start_rescue_watchdog(state_path: str, version_ref: list,
                          rescued_ref: list, total_tasks: int) -> threading.Thread:
    """Start the 1-min rescue watchdog as a daemon thread."""
    _watchdog_stop.clear()
    t = threading.Thread(
        target=_rescue_watchdog,
        args=(state_path, version_ref, rescued_ref, total_tasks),
        daemon=True, name="rescue-watchdog"
    )
    t.start()
    return t

# ── Routing: category → agent module ──────────────────────────────────────
CATEGORY_AGENT_MAP = {
    "code_gen":  "executor",
    "bug_fix":   "executor",
    "debug":     "debugger",
    "tdd":       "test_engineer",
    "scaffold":  "architect",
    "arch":      "architect",
    "refactor":  "refactor",
    "e2e":       "architect",
    "research":  "researcher",
    "doc":       "doc_writer",
    "documentation": "doc_writer",
}

_agent_cache = {}

def _get_agent(name: str):
    """Lazy-load agent module."""
    if name not in _agent_cache:
        import importlib
        mod = importlib.import_module(f"agents.{name}")
        _agent_cache[name] = mod
    return _agent_cache[name]


def route_task(task: dict):
    """Return the agent module for this task's category."""
    category = task.get("category", "code_gen")
    agent_name = CATEGORY_AGENT_MAP.get(category, "executor")
    return _get_agent(agent_name), agent_name


def _check_claude_rescue_eligible(task: dict, fail_count: int,
                                   rescued_so_far: int, total_tasks: int) -> tuple:
    """3-point check before any Claude rescue call. Returns (eligible, reason)."""
    category = task.get("category", "")

    # Check 1: blocked enough times?
    if fail_count < RESCUE_BLOCK_COUNT:
        return False, f"only failed {fail_count}/{RESCUE_BLOCK_COUNT} times"

    # Check 2: budget available?
    budget_used = rescued_so_far / max(total_tasks, 1)
    if budget_used >= CLAUDE_RESCUE_BUDGET:
        return False, f"rescue budget exhausted ({rescued_so_far}/{total_tasks} = {budget_used:.1%})"

    # Check 3: category eligible?
    if category in RESCUE_INELIGIBLE_CATS:
        return False, f"category '{category}' is handled locally only"

    return True, "eligible"


# CLAUDE_TOKEN_CAP defined above in guardrail config section

def _read_agent_file(agent_name: str) -> str:
    """Read the agent's Python source."""
    path = os.path.join(BASE_DIR, "agents", f"{agent_name}.py")
    try:
        with open(path) as f:
            return f.read()
    except Exception:
        return ""


def _write_agent_file(agent_name: str, content: str):
    path = os.path.join(BASE_DIR, "agents", f"{agent_name}.py")
    with open(path, "w") as f:
        f.write(content)


def _bump_agent_version(agent_name: str, from_ver: int) -> int:
    """Bump version in registry/agents.json. Returns new version."""
    try:
        with open(REGISTRY) as f:
            reg = json.load(f)
        new_ver = from_ver + 1
        if agent_name in reg.get("agents", {}):
            reg["agents"][agent_name]["version"] = new_ver
            reg["agents"][agent_name]["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        with open(REGISTRY, "w") as f:
            json.dump(reg, f, indent=2)
        return new_ver
    except Exception:
        return from_ver + 1


def _claude_rescue(task: dict, version: int, agent_name: str,
                    failure_log: list) -> dict:
    """
    Claude rescue = UPGRADE THE AGENT, not the task.

    Protocol:
    1. Read the failure log for this agent
    2. Identify the exact gap in agent's prompt or logic
    3. Write the SMALLEST possible upgrade to agent's system prompt or logic
    4. Push upgrade to agent file + bump version in registry
    5. Hand back to local agent to rerun the task
    6. Log to reports/claude_rescue_upgrades.jsonl
    7. Go silent

    Hard limits: 200 token cap. Never patches the task directly.
    If agent fails again after upgrade, mark upgrade as failed, try different approach.
    """
    title       = task.get("title", "")
    category    = task.get("category", "code_gen")
    agent_src   = _read_agent_file(agent_name)[:1500]  # first 1500 chars for context

    # Build failure summary (last 3 failures max)
    failure_summary = "\n".join([
        f"- Attempt {i+1}: {f.get('tried', str(f))[:100]}"
        for i, f in enumerate(failure_log[-3:])
    ])

    # Tight prompt using agent-upgrade skill protocol — 200 token hard cap
    prompt = (
        f"Agent '{agent_name}' failed task '{title}' (category: {category}) 3 times.\n"
        f"Failures:\n{failure_summary}\n\n"
        f"Agent source (excerpt):\n{agent_src}\n\n"
        f"Diagnose the failure pattern using these fix types:\n"
        f"- placeholder_path → fix: force real absolute paths\n"
        f"- truncated_code → fix: NEVER truncate\n"
        f"- missing_assertions → fix: require __main__ + 3 asserts\n"
        f"- wrong_command → fix: use python3 not python\n"
        f"- hallucinated_import → fix: only use stdlib imports\n"
        f"- syntax_error → fix: require py_compile check\n\n"
        f"Output ONLY:\n"
        f"FIX: <one sentence < 200 chars to add to SYSTEM_PROMPT>\n"
        f"PATTERN: <snake_case pattern name>\n"
        f"DIMENSION: <plan_accuracy|code_correctness|hallucination|actionability>"
    )

    # Dashboard: show benchmarker as "upgrading" (Claude rescue in progress)
    update_agent("benchmarker", "upgrading",
                 f"[CLAUDE RESCUE] {title[:40]}", task.get("id"))

    start      = time.time()
    version_in_reg = 1
    try:
        with open(REGISTRY) as f:
            reg = json.load(f)
        version_in_reg = reg.get("agents", {}).get(agent_name, {}).get("version", 1)
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", "claude-opus-4-6"],
            capture_output=True, text=True, timeout=60
        )
        output = result.stdout or ""
        tokens = len(output) // 4

        # Enforce 200-token cap
        if tokens > CLAUDE_TOKEN_CAP:
            output = output[:CLAUDE_TOKEN_CAP * 4]
            tokens = CLAUDE_TOKEN_CAP

        # Parse the fix
        fix_text     = ""
        pattern_name = ""
        for line in output.splitlines():
            if line.startswith("FIX:"):
                fix_text = line[4:].strip()
            elif line.startswith("PATTERN:"):
                pattern_name = line[8:].strip()

        # Apply the fix: inject into agent's LLM prompt
        new_version = version_in_reg
        upgrade_applied = False
        if fix_text and agent_src:
            # Find the system prompt string in the agent and append fix
            needle = "def run(task: dict) -> dict:"
            if needle in agent_src:
                fix_comment = f"\n    # [UPGRADE v{version_in_reg+1}] {fix_text}\n"
                new_src = agent_src.replace(needle, fix_comment + needle, 1)
                # Re-read full agent to patch (excerpt was truncated)
                full_src = _read_agent_file(agent_name)
                if needle in full_src:
                    patched = full_src.replace(needle, fix_comment + needle, 1)
                    _write_agent_file(agent_name, patched)
                    new_version = _bump_agent_version(agent_name, version_in_reg)
                    upgrade_applied = True
                    # Invalidate agent cache so it reloads
                    _agent_cache.pop(agent_name, None)

        # Log to claude_rescue_upgrades.jsonl
        elapsed = round(time.time() - start, 1)
        upgrade_record = {
            "ts": datetime.now().isoformat(),
            "version": version,
            "agent": agent_name,
            "version_before": version_in_reg,
            "version_after": new_version,
            "failure_pattern": pattern_name or "unknown",
            "fix_applied": fix_text[:200],
            "upgrade_applied": upgrade_applied,
            "tokens": tokens,
            "task_id": task.get("id"),
            "title": title[:80],
            "elapsed_s": elapsed,
        }
        log_path = os.path.join(REPORTS_DIR, "claude_rescue_upgrades.jsonl")
        with open(log_path, "a") as f:
            f.write(json.dumps(upgrade_record) + "\n")

        # Also log to token log
        token_record = {
            "ts": datetime.now().isoformat(), "version": version,
            "task_id": task.get("id"), "title": title[:80],
            "reason": "agent_upgrade", "tokens": tokens,
            "agent": agent_name, "elapsed_s": elapsed,
        }
        with open(os.path.join(REPORTS_DIR, "claude_token_log.jsonl"), "a") as f:
            f.write(json.dumps(token_record) + "\n")

        print(f"    [UPGRADE] Agent '{agent_name}' v{version_in_reg}→v{new_version}: {pattern_name}")
        print(f"    [UPGRADE] Fix: {fix_text[:80]}")
        print(f"    [UPGRADE] Tokens used: {tokens}/{CLAUDE_TOKEN_CAP}")

        # Dashboard: rescue complete — reset benchmarker to idle
        update_agent("benchmarker", "idle", "", None)

        # Return signal to rerun the task with the upgraded agent
        return {
            "status": "upgraded",
            "upgrade_applied": upgrade_applied,
            "new_version": new_version,
            "tokens_used": tokens,
            "elapsed_s": elapsed,
            "agent": "claude_rescue",
            "fix": fix_text,
        }

    except FileNotFoundError:
        update_agent("benchmarker", "idle", "", None)
        return {"status": "no_cli", "upgrade_applied": False,
                "tokens_used": 0, "agent": "claude_rescue",
                "error": "claude CLI not found"}
    except Exception as e:
        update_agent("benchmarker", "idle", "", None)
        return {"status": "error", "upgrade_applied": False,
                "tokens_used": 0, "agent": "claude_rescue", "error": str(e)}


def run_task_with_fallback(task: dict, version: int,
                           rescued_count: int, total_tasks: int) -> dict:
    """
    Run a task through autonomous execution with full self-governance.

    AutonomousExecutor handles:
    1. Adaptive budgeting (gets today's adjusted budget for agent)
    2. Task difficulty adjustment (based on agent success rate)
    3. Execution with retries (max 3 attempts)
    4. Output validation (enforces contract)
    5. Auto-remediation (reduces difficulty, escalates denials, etc.)
    6. Success rate tracking (for budget adjustments)

    FIX 5: Enforce 3-attempt rescue gate before Claude escalation.
    Claude rescue is NO LONGER CALLED — all autonomy is local.
    """
    from state.runtime_lessons import log_attempt, can_escalate_to_rescue, mark_rescued

    agent_mod, agent_name = route_task(task)
    task_id = task.get("id", "unknown")

    # Use autonomous executor for full self-governance
    if _AUTONOMOUS_EXECUTOR:
        executor = AutonomousExecutor(state_dir=os.path.join(BASE_DIR, "state"))
        result = executor.execute_task(task, agent_mod, version=version, max_retries=3)

        # Log attempt to runtime-lessons
        success = result.get("status") == "done" and result.get("quality", 0) >= 30
        error = result.get("error") if not success else None
        strategy = result.get("strategy", "autonomous")
        log_attempt(task_id, strategy, error=error, success=success)

        # Check if we should escalate to rescue
        if not success and can_escalate_to_rescue(task_id, max_attempts=3):
            # TASK-FIX-5: Check token enforcer before allowing rescue
            if _TOKEN_ENFORCER and not is_rescue_allowed(task_id):
                print(f"[RESCUE GATE] Task {task_id} blocked by token enforcer (budget exhausted)")
                result["rescue_eligible"] = False
            else:
                print(f"[RESCUE GATE] Task {task_id} escalated after 3 attempts")
                mark_rescued(task_id)
                result["rescue_eligible"] = True
        else:
            result["rescue_eligible"] = False

        # Add orchestrator metadata
        result["agent_used"] = agent_name
        result["version"] = version
        return result

    # Fallback to simple execution (if AutonomousExecutor unavailable)
    result = agent_mod.run(task)
    result["agent_used"] = agent_name
    result["version"] = version
    result["autonomous"] = False
    return result
def _write_leaderboard(version: int, avg_local: float, avg_opus: float,
                       win_rate: float, gap: float):
    """Append version result to docs/leaderboard.md for human-readable progress."""
    lb_path = os.path.join(os.path.dirname(BASE_DIR), "docs", "leaderboard.md")
    try:
        os.makedirs(os.path.dirname(lb_path), exist_ok=True)
        # Read existing content or create header
        try:
            with open(lb_path) as f:
                lines = f.readlines()
        except FileNotFoundError:
            lines = [
                "# Nexus vs Opus 4.6 — Leaderboard\n\n",
                "Auto-updated after every version. Local = Nexus. Target: beat Opus 4.6 on all categories.\n\n",
                "| Version | Local avg | Opus avg | Gap | Win Rate | Status |\n",
                "|---------|-----------|----------|-----|----------|--------|\n",
            ]
        # Append new row
        status = "WIN" if avg_local >= avg_opus else f"GAP {gap:+.0f}"
        row = f"| v{version} | {avg_local}/100 | {avg_opus}/100 | {gap:+.1f} | {win_rate}% | {status} |\n"
        lines.append(row)
        with open(lb_path, "w") as f:
            f.writelines(lines)
    except Exception as e:
        print(f"[LEADERBOARD] write error: {e}")


def _update_projects_json_task(task_id: str, status: str, quality_score: float,
                                elapsed_seconds: float = 0):
    """Update task status in projects.json (PERSISTENCE LAYER FIX)."""
    projects_file = os.path.join(BASE_DIR, "projects.json")
    try:
        with open(projects_file, "r") as f:
            data = json.load(f)

        # Find and update the task
        for project in data.get("projects", []):
            for task in project.get("tasks", []):
                if task.get("id") == task_id:
                    task["status"] = status
                    task["quality_score"] = quality_score
                    task["elapsed_seconds"] = elapsed_seconds
                    task["completed_at"] = datetime.now().isoformat() if status == "completed" else None

                    # Write back to projects.json
                    with open(projects_file, "w") as f:
                        json.dump(data, f, indent=2)

                    print(f"[PERSISTENCE] Updated {task_id}: status={status}, quality={quality_score}")
                    return True

        print(f"[PERSISTENCE] WARNING: Task {task_id} not found in projects.json")
        return False
    except Exception as e:
        print(f"[PERSISTENCE] ERROR: Failed to update projects.json: {e}")
        return False


def run_version(version: int, tasks: list, local_only: bool = False,
                quick: int = 0) -> dict:
    """Run one benchmark version. Returns version summary."""
    # ── 0. Start auto-heal monitor (idempotent — won't double-start) ──────────
    ah = _get_auto_heal()
    ah.start()

    # ── 1. Supervisor pre-flight ──────────────────────────────────────────────
    if _SUPERVISOR_AVAILABLE:
        sv = _get_sv()
        pf = sv.pre_flight_check(version, tasks[:quick] if quick else tasks)
        if pf.blocked:
            print(f"[SUPERVISOR] Pre-flight BLOCKED — aborting v{version}")
            return {"version": version, "blocked": True, "tasks_run": 0}

    # ── 2. Snapshot system state BEFORE upgrades (for rollback safety) ────────
    cm = _get_cm()
    cm.snapshot_version(version)

    # ── 3. Self-calibration: 3-task warmup, gate agents before task pool ──────
    pe = _get_pe()
    if _CALIBRATION:
        import importlib, sys as _sys
        agent_mods = {}
        for aname in ["executor","planner","reviewer","debugger","researcher",
                      "benchmarker","architect","refactor","test_engineer","doc_writer"]:
            try:
                mod = importlib.import_module(f"agents.{aname}")
                agent_mods[aname] = mod
            except ImportError:
                pass
        cal_results = _calibrate(version, agent_mods)
        passing_agents = get_passing_agents(cal_results)
        print(f"[CALIBRATION] Passing agents: {sorted(passing_agents)}")
    else:
        passing_agents = set()

    guard        = ResourceGuard()
    report_path  = os.path.join(REPORTS_DIR, f"v{version}_compare.jsonl")
    token_path   = os.path.join(REPORTS_DIR, "token_comparison.jsonl")

    if quick:
        tasks = tasks[:quick]

    total_tasks        = len(tasks)
    rescued_count      = 0
    local_wins         = 0
    results            = []
    total_local_qual   = 0
    total_opus_qual    = 0

    print(f"\n{'='*60}")
    print(f"[ORCHESTRATOR] v{version} — {total_tasks} tasks")
    print(f"{'='*60}")

    # ── Board pre-population: write ALL tasks to dashboard BEFORE any agent moves ──
    # Technical + non-technical stakeholders see the complete plan immediately.
    if _BOARD_INIT:
        _init_board(tasks, version=version)

    # Dashboard: version start
    update_version(version, 100, f"v{version} running")
    update_task_queue(total_tasks, 0, 0, 0, total_tasks)

    # ── Adaptive budgeting: adjust budgets daily based on success rates ──
    ab = None
    if _ADAPTIVE_BUDGETING:
        ab = AdaptiveBudgeting(state_dir=os.path.join(BASE_DIR, "state"))
        adjustments = ab.check_and_adjust()
        if adjustments:
            print(f"[BUDGETING] Daily adjustments:")
            for agent, (old, new, reason) in adjustments.items():
                print(f"  {agent}: {old} → {new} tokens ({reason})")

    completed = 0
    failed_count = 0

    for i, task in enumerate(tasks, 1):
        # FIX 3: Skip done tasks — prevent re-runs
        # P0 FIX: Use normalize_task_status to handle all status format variations
        task_status = normalize_task_status(task.get("status", task.get("is_done", False)))
        if task_status == "completed" or task.get("is_done") == True:
            print(f"  [{i:3}/{total_tasks}] SKIP (status={task_status})")
            completed += 1
            continue

        # Resource check + dashboard hardware update (cpu first, then ram per signature)
        status = guard.check()
        update_hardware(status.cpu_pct, status.ram_pct)
        if not status.can_spawn:
            print(f"  [RESOURCE] {status.action.upper()} — RAM={status.ram_pct}% — waiting...")
            guard.wait_for_headroom(max_wait=120)

        category = task.get("category", "code_gen")
        title    = task.get("title", "")
        task_id  = task.get("id", i)
        print(f"  [{i:3}/{total_tasks}] {category:10} | {title[:50]}")

        # Mark agent as running in dashboard + board
        agent_name_hint = CATEGORY_AGENT_MAP.get(category, "executor")
        update_agent(agent_name_hint, "running", title[:60], task_id)
        update_task_queue(total_tasks, completed, 1, failed_count, total_tasks - completed - 1)
        if _BOARD_INIT:
            _update_task_status(task_id, "running", 0, 0.0, agent_name_hint)

        # Run local agent
        local_result = run_task_with_fallback(
            task, version, rescued_count, total_tasks
        )
        if local_result.get("claude_rescued"):
            rescued_count += 1
            # Log Claude token usage to dashboard (rescue only — cumulative)
            update_token_usage(rescued_count, total_tasks - rescued_count, total_tasks)

        local_quality = local_result.get("quality", 0)

        # Update completed/failed counts
        # P0 FIX: Use normalize_task_status to handle all status format variations
        result_status = normalize_task_status(local_result.get("status", "pending"))
        task_successful = result_status == "completed" and local_quality >= 30
        if task_successful:
            completed += 1
            # ★ PERSISTENCE LAYER FIX: Update projects.json with completed task ★
            elapsed = local_result.get("elapsed_s", 0.0)
            _update_projects_json_task(str(task_id), "completed", local_quality, elapsed)
        else:
            failed_count += 1
            # Handle case where agent returns None
            if local_result is None:
                error_msg = "Agent returned None (crashed or timed out)"
            elif isinstance(local_result, dict):
                error_msg = (local_result.get("error") or
                            local_result.get("status") or
                            "failed")
            else:
                error_msg = str(local_result)

            log_failure(agent_name_hint, title[:80], task_id, 1,
                        (error_msg[:200] if isinstance(error_msg, str) else str(error_msg)[:200]) if error_msg else "unknown error")

        # ── Update adaptive budgeting with task outcome ──
        if ab:
            agent_used = local_result.get("agent_used", agent_name_hint)
            tokens_used = local_result.get("tokens_used", local_result.get("tokens", 0))
            ab.update_success_rate(agent_used, successful=task_successful, tokens_used=tokens_used)

        # Update queue counts (keep agent status as result of run)
        # P0 FIX: Use normalized status for consistent state tracking
        status_after = "done" if result_status == "completed" else "blocked"
        update_agent(agent_name_hint, status_after, f"[{local_quality}/100] {title[:50]}", task_id)
        update_task_queue(total_tasks, completed, 0, failed_count, total_tasks - completed - failed_count)

        # Update task on board — real-time stakeholder visibility
        if _BOARD_INIT:
            _update_task_status(task_id, status_after, local_quality,
                                local_result.get("elapsed_s", 0.0), agent_name_hint)

        # Run Opus 4.6 baseline (skip if local_only)
        opus_quality = 0
        opus_result  = {}
        if not local_only:
            try:
                update_agent("reviewer", "reviewing", f"Opus 4.6 ← {title[:40]}", task_id)
                from opus_runner import run_opus_task
                opus_result  = run_opus_task(task, version)
                opus_quality = opus_result.get("quality", 0)
                update_agent("reviewer", "idle", "", None)
            except Exception as e:
                print(f"    [OPUS] Error: {e}")
                update_agent("reviewer", "idle", "", None)
                opus_quality = 70  # assume Opus would score ~70 on average

        total_local_qual += local_quality
        total_opus_qual  += opus_quality
        if local_quality >= opus_quality - 5:
            local_wins += 1

        # ── Prompt engine: record result, A/B test after low-quality tasks ──
        if _PROMPT_ENGINE:
            version_avg_so_far = (total_local_qual / max(completed + 1, 1))
            improved = pe.record_task(
                local_result.get("agent_used", "executor"),
                task, local_result, version_avg=version_avg_so_far
            )
            pe.record_ab_result(
                local_result.get("agent_used", "executor"), local_quality
            )

        # Log comparison
        record = {
            "ts":             datetime.now().isoformat(),
            "version":        version,
            "task_id":        task.get("id", i),
            "title":          task.get("title", "")[:80],
            "category":       category,
            "local_quality":  local_quality,
            "opus_quality":   opus_quality,
            "gap":            round(opus_quality - local_quality, 1),
            "local_won":      local_quality >= opus_quality - 5,
            "claude_rescued": local_result.get("claude_rescued", False),
            "agent_used":     local_result.get("agent_used", "unknown"),
            "fail_count":     local_result.get("fail_count", 0),
            "local_elapsed":  local_result.get("elapsed_s", 0),
        }
        results.append(record)
        with open(report_path, "a") as f:
            f.write(json.dumps(record) + "\n")

        # Log token comparison
        token_record = {
            "ts": record["ts"], "version": version, "task_id": record["task_id"],
            "local_tokens": local_result.get("tokens_used", local_result.get("tokens", 0)),
            "opus_tokens":  opus_result.get("tokens_used", opus_result.get("tokens", 0)),
            "claude_rescue_tokens": 0,
        }
        with open(token_path, "a") as f:
            f.write(json.dumps(token_record) + "\n")

        # Progress line
        gap = opus_quality - local_quality
        indicator = "WIN" if local_quality >= opus_quality - 5 else f"GAP={gap:+.0f}"
        print(f"         local={local_quality:3}/100  opus={opus_quality:3}/100  {indicator}"
              + ("  [CLAUDE RESCUED]" if local_result.get("claude_rescued") else ""))

    win_rate = round(local_wins / total_tasks * 100, 1) if total_tasks else 0
    rescue_rate = round(rescued_count / total_tasks * 100, 1) if total_tasks else 0

    summary = {
        "version":      version,
        "tasks_run":    total_tasks,
        "local_wins":   local_wins,
        "win_rate":     win_rate,
        "rescued":      rescued_count,
        "rescue_rate":  rescue_rate,
        "local_beats_opus": win_rate >= 95.0,
    }

    avg_local = round(total_local_qual / total_tasks, 1) if total_tasks else 0
    avg_opus  = round(total_opus_qual  / total_tasks, 1) if total_tasks else 0
    gap       = round(avg_local - avg_opus, 1)

    # Dashboard: final version state
    update_version(version, 100, f"v{version} complete — win_rate={win_rate}%")
    update_task_queue(total_tasks, completed, 0, failed_count, 0)
    update_benchmark_score(version, avg_local, avg_opus, win_rate, gap)
    update_version_changelog(version, [f"win_rate={win_rate}%", f"local_avg={avg_local}",
                                        f"opus_avg={avg_opus}", f"rescued={rescue_rate}%",
                                        f"tasks={total_tasks}"], avg_opus, avg_local)

    # Write leaderboard.md
    _write_leaderboard(version, avg_local, avg_opus, win_rate, gap)

    print(f"\n[v{version} SUMMARY] win_rate={win_rate}%  local={avg_local}/100  opus={avg_opus}/100  gap={gap:+}  rescued={rescue_rate}%")

    summary["avg_local"] = avg_local
    summary["avg_opus"]  = avg_opus
    summary["gap"]       = gap

    # ── Regression check + auto-rollback ─────────────────────────────────────
    if _CHECKPOINT:
        cm = _get_cm()
        if cm.has_regressed(version, metric="avg_local"):
            print(f"[ROLLBACK] v{version} regressed on avg_local — rolling back to pre-v{version} snapshot")
            ok = cm.rollback_version(version)
            if ok:
                print(f"[ROLLBACK] Rolled back successfully. v{version+1} will start from clean snapshot.")
            else:
                print(f"[ROLLBACK] No snapshot found for v{version} — continuing with current state")

    return summary


def _write_version_file(version: int):
    """Sync VERSION file with current runtime version (0.{version}.0 format)."""
    ver_path = os.path.join(os.path.dirname(BASE_DIR), "VERSION")
    try:
        with open(ver_path, "w") as f:
            f.write(f"0.{version}.0\n")
    except Exception:
        pass


def auto_loop(start_version: int):
    """Full autonomous v{start}→v1000 loop. Self-improves until beating Opus 4.6."""
    # Load tasks from both task_suite.py (legacy) and projects.json (new)
    from tasks.task_suite import build_task_suite
    from orchestrator.projects_loader import load_projects_tasks

    # CRITICAL FIX: Load projects.json tasks FIRST (higher priority)
    # This ensures they execute when running in quick mode
    project_tasks = load_projects_tasks()

    if project_tasks:
        print(f"[PROJECTS] Prioritizing {len(project_tasks)} tasks from projects.json")
        tasks = project_tasks
    else:
        tasks = []

    # Add task_suite tasks second (lower priority, for testing)
    suite_tasks = build_task_suite()
    tasks.extend(suite_tasks)
    print(f"[PROJECTS] Total task queue: {len(project_tasks)} projects + {len(suite_tasks)} suite = {len(tasks)} tasks")

    # Start 1-minute rescue watchdog in background
    state_path   = os.path.join(BASE_DIR, "dashboard", "state.json")
    version_ref  = [start_version]   # mutable ref so watchdog sees current version
    rescued_ref  = [0]
    start_rescue_watchdog(state_path, version_ref, rescued_ref, len(tasks))
    print(f"[WATCHDOG] Rescue watchdog active — checks every {_WATCHDOG_INTERVAL}s")

    for version in range(start_version, 1001):
        version_ref[0] = version
        # Every 5 versions: frustration research
        if version % 5 == 0:
            try:
                sys.path.insert(0, BENCHMARKS)
                from frustration_research import run as research_run, apply_patches
                findings = research_run(version)
                apply_patches(findings)
                # Push research findings to dashboard
                for complaint in (findings.get("top_complaints") or [])[:5]:
                    log_research(f"v{version}: {complaint}")
            except Exception as e:
                print(f"[RESEARCH] Error at v{version}: {e}")

        summary = run_version(version, tasks)
        _write_version_file(version)  # sync VERSION file with current runtime version

        # Self-improving prompt engine: auto-upgrade agents from this version's failures
        if _AUTO_UPGRADE:
            try:
                report_path = os.path.join(REPORTS_DIR, f"v{version}_compare.jsonl")
                v_results = []
                if os.path.exists(report_path):
                    with open(report_path) as f:
                        for line in f:
                            try:
                                v_results.append(json.loads(line))
                            except Exception:
                                pass
                if v_results:
                    upgrades = _auto_upgrade(version, v_results, top_n=3)
                    if upgrades:
                        print(f"[AUTO-UPGRADE] {len(upgrades)} prompt fixes applied for v{version+1}")
            except Exception as e:
                print(f"[AUTO-UPGRADE] Error: {e}")

        # Gap analysis + upgrade
        analysis = analyze_version(version)
        if analysis.get("local_wins"):
            print(f"\n{'='*60}")
            print(f"LOCAL AGENTS BEAT OPUS 4.6 at v{version}!")
            print(f"win_rate={summary['win_rate']}%")
            print(f"{'='*60}")
            break

        if analysis.get("upgrade_needed"):
            print(f"\n[UPGRADE] Triggering upgrade v{version}→v{version+1}...")
            try:
                subprocess.run(
                    ["python3", os.path.join(BASE_DIR, "upgrade_agent.py"),
                     "--from", str(version), "--to", str(version + 1)],
                    cwd=BASE_DIR, timeout=120
                )
            except Exception as e:
                print(f"[UPGRADE] Error: {e}")

        # Calculate and display ETA
        try:
            subprocess.run(
                ["python3", os.path.join(BASE_DIR, "scripts", "eta_calculator.py")],
                cwd=BASE_DIR, timeout=10, capture_output=True
            )
        except Exception as e:
            pass  # ETA calculation is optional, don't block loop

        time.sleep(2)


def main():
    ap = argparse.ArgumentParser(description="Local Agent Upgrade Orchestrator v1→v100")
    ap.add_argument("--version", type=int, default=1, help="Start version")
    ap.add_argument("--auto",    type=int, default=0, metavar="START",
                    help="Full auto loop from START to v100")
    ap.add_argument("--quick",   type=int, default=0, metavar="N",
                    help="Run only N tasks (for testing)")
    ap.add_argument("--local-only", action="store_true",
                    help="Skip Opus 4.6 comparison (free run)")
    args = ap.parse_args()

    if args.auto:
        auto_loop(args.auto)
        return

    from tasks.task_suite import build_task_suite
    from orchestrator.projects_loader import load_projects_tasks

    # CRITICAL FIX: Load projects.json tasks FIRST (higher priority)
    # This ensures they execute when --quick N is used
    project_tasks = load_projects_tasks()

    if project_tasks:
        print(f"[PROJECTS] Prioritizing {len(project_tasks)} tasks from projects.json")
        tasks = project_tasks  # Start with projects
    else:
        tasks = []

    # Add task_suite tasks second (lower priority, for testing)
    suite_tasks = build_task_suite()
    tasks.extend(suite_tasks)
    print(f"[PROJECTS] Total task queue: {len(project_tasks)} projects + {len(suite_tasks)} suite = {len(tasks)} tasks")

    run_version(args.version, tasks, local_only=args.local_only, quick=args.quick)


if __name__ == "__main__":
    main()
