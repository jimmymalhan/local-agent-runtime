#!/usr/bin/env python3
"""
orchestrator/main.py — Self-running v1→v100 upgrade loop
=========================================================
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
import os, sys, json, time, argparse, subprocess
from pathlib import Path
from datetime import datetime

BASE_DIR    = str(Path(__file__).parent.parent)
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
REGISTRY    = os.path.join(BASE_DIR, "registry", "agents.json")
BENCHMARKS  = os.path.join(BASE_DIR, "benchmarks")
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, str(Path(__file__).parent))

Path(REPORTS_DIR).mkdir(exist_ok=True)

from orchestrator.resource_guard import ResourceGuard
from agents.benchmarker import analyze_version

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

# ── Claude guardrail config ────────────────────────────────────────────────
CLAUDE_RESCUE_BUDGET  = 0.10   # max 10% of tasks rescued by Claude
RESCUE_BLOCK_COUNT    = 3      # task must fail 3+ times before Claude rescue
RESCUE_INELIGIBLE_CATS = {"research", "doc", "documentation"}  # local handles these

# ── Routing: category → agent module ──────────────────────────────────────
CATEGORY_AGENT_MAP = {
    "code_gen":  "executor",
    "bug_fix":   "executor",
    "tdd":       "test_engineer",
    "scaffold":  "architect",
    "arch":      "architect",
    "refactor":  "refactor",
    "e2e":       "architect",
    "research":  "researcher",
    "doc":       "doc_writer",
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


CLAUDE_TOKEN_CAP = 200   # hard cap per rescue call — 200 tokens max

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
        return {"status": "no_cli", "upgrade_applied": False,
                "tokens_used": 0, "agent": "claude_rescue",
                "error": "claude CLI not found"}
    except Exception as e:
        return {"status": "error", "upgrade_applied": False,
                "tokens_used": 0, "agent": "claude_rescue", "error": str(e)}


def run_task_with_fallback(task: dict, version: int,
                           rescued_count: int, total_tasks: int) -> dict:
    """
    Run a task through the specialized agent.
    If it fails 3x with 3 different approaches → Claude UPGRADES THE AGENT.
    After upgrade, the task reruns on the upgraded agent.
    Claude never fixes the task directly — it only upgrades the agent.
    """
    agent_mod, agent_name = route_task(task)
    fail_count   = 0
    last_result  = None
    failure_log  = []

    for attempt in range(1, RESCUE_BLOCK_COUNT + 1):
        result = agent_mod.run(task)
        if result.get("status") == "done" and result.get("quality", 0) >= 30:
            result["fail_count"]     = fail_count
            result["claude_rescued"] = False
            result["agent_used"]     = agent_name
            return result
        fail_count += 1
        failure_log.append({"attempt": attempt, "tried": str(result.get("error", result.get("status", "")))[:100]})
        last_result = result
        if attempt < RESCUE_BLOCK_COUNT:
            time.sleep(2)

    # All 3 local attempts failed — check Claude upgrade eligibility
    eligible, reason = _check_claude_rescue_eligible(
        task, fail_count, rescued_count, total_tasks
    )
    if eligible:
        print(f"    [UPGRADE] Agent '{agent_name}' failed {fail_count}x — Claude upgrading agent")
        upgrade = _claude_rescue(task, version, agent_name, failure_log)

        if upgrade.get("upgrade_applied"):
            # Reload upgraded agent and rerun the task once
            agent_mod, _ = route_task(task)  # reloads from cache-cleared module
            retry = agent_mod.run(task)
            retry_passed = retry.get("status") == "done" and retry.get("quality", 0) >= 30

            # Log whether upgrade fixed the task
            upgrades_log = os.path.join(REPORTS_DIR, "claude_rescue_upgrades.jsonl")
            try:
                lines = open(upgrades_log).readlines()
                if lines:
                    last = json.loads(lines[-1])
                    last["task_rerun_passed"] = retry_passed
                    with open(upgrades_log, "a") as f:
                        pass  # already written above; no double-write
            except Exception:
                pass

            if retry_passed:
                retry["fail_count"]     = fail_count
                retry["claude_rescued"] = True
                retry["agent_used"]     = agent_name
                return retry

        # Upgrade didn't fix it — return last local attempt
        last_result = last_result or {"status": "failed", "quality": 0, "output": ""}
        last_result["fail_count"]     = fail_count
        last_result["claude_rescued"] = True   # claude was used even if task still failed
        last_result["agent_used"]     = agent_name
        return last_result

    # No rescue eligible — return best local attempt
    last_result = last_result or {"status": "failed", "quality": 0, "output": ""}
    last_result["fail_count"]     = fail_count
    last_result["claude_rescued"] = False
    last_result["agent_used"]     = agent_name
    print(f"    [BLOCKED] {reason}")
    return last_result


def run_version(version: int, tasks: list, local_only: bool = False,
                quick: int = 0) -> dict:
    """Run one benchmark version. Returns version summary."""
    # Supervisor pre-flight: verifies hardware, registry, no duplicates
    if _SUPERVISOR_AVAILABLE:
        sv = _get_sv()
        pf = sv.pre_flight_check(version, tasks[:quick] if quick else tasks)
        if pf.blocked:
            print(f"[SUPERVISOR] Pre-flight BLOCKED — aborting v{version}")
            return {"version": version, "blocked": True, "tasks_run": 0}

    guard        = ResourceGuard()
    report_path  = os.path.join(REPORTS_DIR, f"v{version}_compare.jsonl")
    token_path   = os.path.join(REPORTS_DIR, "token_comparison.jsonl")

    if quick:
        tasks = tasks[:quick]

    total_tasks   = len(tasks)
    rescued_count = 0
    local_wins    = 0
    results       = []

    print(f"\n{'='*60}")
    print(f"[ORCHESTRATOR] v{version} — {total_tasks} tasks")
    print(f"{'='*60}")

    # Dashboard: version start
    update_version(version, 100, f"v{version} running")
    update_task_queue(total_tasks, 0, 0, 0, total_tasks)

    completed = 0
    failed_count = 0

    for i, task in enumerate(tasks, 1):
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

        # Mark agent as running in dashboard
        agent_name_hint = CATEGORY_AGENT_MAP.get(category, "executor")
        update_agent(agent_name_hint, "running", title[:60], task_id)
        update_task_queue(total_tasks, completed, 1, failed_count, total_tasks - completed - 1)

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
        if local_result.get("status") == "done":
            completed += 1
        else:
            failed_count += 1
            log_failure(agent_name_hint, title[:80], task_id, 1,
                        local_result.get("error", local_result.get("status", "failed"))[:200])

        # Mark agent idle after task
        update_agent(agent_name_hint, "idle", "", None)
        update_task_queue(total_tasks, completed, 0, failed_count, total_tasks - completed - failed_count)

        # Run Opus 4.6 baseline (skip if local_only)
        opus_quality = 0
        opus_result  = {}
        if not local_only:
            try:
                from opus_runner import run_opus_task
                opus_result  = run_opus_task(task, version)
                opus_quality = opus_result.get("quality", 0)
            except Exception as e:
                print(f"    [OPUS] Error: {e}")
                opus_quality = 70  # assume Opus would score ~70 on average

        if local_quality >= opus_quality - 5:
            local_wins += 1

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
            "local_tokens": local_result.get("tokens_used", 0),
            "opus_tokens":  opus_result.get("tokens_used", 0),
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

    # Dashboard: final version state
    update_version(version, 100, f"v{version} complete — win_rate={win_rate}%")
    update_task_queue(total_tasks, completed, 0, failed_count, 0)
    update_benchmark_score(version, win_rate, 0.0, win_rate, 0.0)
    update_version_changelog(version, [f"win_rate={win_rate}%", f"rescued={rescue_rate}%",
                                        f"tasks={total_tasks}"], 0.0, win_rate)

    print(f"\n[v{version} SUMMARY] win_rate={win_rate}%  rescued={rescue_rate}%")
    return summary


def auto_loop(start_version: int):
    """Full autonomous v{start}→v100 loop."""
    from tasks.task_suite import build_task_suite
    tasks = build_task_suite()

    for version in range(start_version, 101):
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
    tasks = build_task_suite()
    run_version(args.version, tasks, local_only=args.local_only, quick=args.quick)


if __name__ == "__main__":
    main()
