#!/usr/bin/env python3
"""
claude_supervisor.py — 3-Minute Watchdog + Teaching Moments
=============================================================
Claude's 10% role: supervise, rescue blocked tasks, log teaching moments.

Runs alongside bench_compare.py (or independently as a background daemon).
Every 180 seconds:
  1. Query task board for blocked/stuck tasks
  2. Rescue any task blocked >120s using Opus 4.6 CLI (≤10% of total tasks)
  3. Print live progress summary with local vs opus quality gap
  4. Log teaching moments (what Claude fixed that local couldn't)
  5. Emit upgrade signal when a category falls below threshold

Usage:
  python3 claude_supervisor.py &                     # background daemon
  python3 claude_supervisor.py --version 4           # supervise v4 benchmark
  python3 claude_supervisor.py --version 4 --once    # single check
  python3 claude_supervisor.py --status              # show current progress
"""
import os, sys, json, time, argparse, subprocess, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

BASE_DIR    = "/Users/jimmymalhan/Documents/local-agent-runtime/local-agents"
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
API         = f"http://127.0.0.1:{os.environ.get('PORT_API', '8000')}"
OPUS_MODEL  = "claude-opus-4-6"

WATCH_INTERVAL   = 180   # seconds between supervisor checks
RESCUE_THRESHOLD = 120   # task must be blocked >120s before rescue
RESCUE_TIMEOUT   = 300   # max seconds for a single Claude rescue
WIN_THRESHOLD    = 5.0   # quality gap that triggers upgrade signal

Path(REPORTS_DIR).mkdir(exist_ok=True)


def api_call(method, path, data=None, timeout=15):
    url = f"{API}{path}"
    body = json.dumps(data).encode() if data else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def get_blocked_tasks(min_age_s: int = RESCUE_THRESHOLD) -> list:
    """Return tasks that have been blocked for longer than min_age_s."""
    tasks = api_call("GET", "/tasks?status=blocked&limit=50") or []
    now = time.time()
    old_tasks = []
    for t in tasks:
        updated = t.get("updated_at", "")
        if updated:
            try:
                from datetime import datetime as dt
                ts = dt.fromisoformat(updated.replace("Z", "+00:00")).timestamp()
                if now - ts > min_age_s:
                    old_tasks.append(t)
            except Exception:
                old_tasks.append(t)
        else:
            old_tasks.append(t)
    return old_tasks


def rescue_with_opus(task: dict) -> dict:
    """Rescue a blocked task using Claude Opus 4.6 CLI."""
    title = task.get("title", "")
    description = task.get("description", title)
    task_id = task.get("id")

    prompt = (
        f"Complete this coding task fully and correctly.\n\n"
        f"TASK: {title}\n\n"
        f"INSTRUCTIONS:\n{description}\n\n"
        f"Write complete, working Python code with all imports and assertions.\n"
        f"Do not truncate. Do not explain. Just write the code.\n"
    )

    start = time.time()
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", OPUS_MODEL],
            capture_output=True, text=True, timeout=RESCUE_TIMEOUT
        )
        elapsed = time.time() - start
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        quality = 50  # base quality for rescue
        if "def " in stdout or "class " in stdout:
            quality += 20
        if result.returncode == 0:
            quality += 15
        if "error" not in (stdout + stderr).lower():
            quality += 15
        quality = min(100, quality)

        record = {
            "ts": datetime.now().isoformat(),
            "task_id": task_id,
            "title": title[:80],
            "elapsed_s": round(elapsed, 1),
            "quality": quality,
            "status": "rescued" if quality >= 50 else "rescue_failed",
            "tokens": len(stdout) // 4,
        }
        with open(os.path.join(REPORTS_DIR, "claude_rescues.jsonl"), "a") as f:
            f.write(json.dumps(record) + "\n")
        if task_id and quality >= 50:
            api_call("PATCH", f"/tasks/{task_id}", {
                "status": "done",
                "notes": f"Rescued by Claude Opus 4.6 (quality={quality}/100)",
                "eval_score": quality,
            })
        return record
    except subprocess.TimeoutExpired:
        return {"task_id": task_id, "status": "rescue_timeout", "quality": 0}
    except FileNotFoundError:
        print("[SUPERVISOR] 'claude' CLI not found")
        return {"task_id": task_id, "status": "no_cli", "quality": 0}
    except Exception as e:
        return {"task_id": task_id, "status": "rescue_error", "quality": 0, "error": str(e)}


def get_version_progress(version: int) -> dict:
    """Load and summarize results for a version."""
    path = os.path.join(REPORTS_DIR, f"v{version}_compare.jsonl")
    if not os.path.exists(path):
        return {}
    results = []
    with open(path) as f:
        for line in f:
            try:
                results.append(json.loads(line.strip()))
            except Exception:
                pass
    if not results:
        return {}
    local_q = sum(r.get("local_quality", 0) for r in results) / len(results)
    opus_q = sum(r.get("opus_quality", 0) for r in results) / len(results)
    rescued = sum(1 for r in results if r.get("claude_rescued"))
    return {
        "tasks_done": len(results),
        "local_avg_quality": round(local_q, 1),
        "opus_avg_quality": round(opus_q, 1),
        "gap": round(opus_q - local_q, 1),
        "rescued": rescued,
        "rescue_pct": round(rescued / len(results) * 100, 1),
        "local_winning": local_q >= opus_q - WIN_THRESHOLD,
    }


def supervision_check(version: int, rescue_budget: float = 0.10,
                      total_tasks: int = 100) -> dict:
    """Perform one supervision check: log progress, rescue blocked tasks."""
    now = datetime.now().strftime("%H:%M:%S")
    print(f"\n[SUPERVISOR v{version}] Check @ {now}")

    progress = get_version_progress(version)
    if progress:
        print(f"  Tasks done: {progress['tasks_done']} | "
              f"local_q={progress['local_avg_quality']}  opus_q={progress['opus_avg_quality']}  "
              f"gap={progress['gap']:+.1f}")
        print(f"  Rescued: {progress['rescued']} ({progress['rescue_pct']}%) | "
              f"local {'WINNING' if progress['local_winning'] else 'BEHIND'}")
        if progress["gap"] > WIN_THRESHOLD:
            print(f"  [SUPERVISOR] Gap {progress['gap']:.1f}pts → upgrade agent after version")

    # Rescue blocked tasks (stay within 10% budget)
    max_rescues = int(total_tasks * rescue_budget)
    rescued_so_far = progress.get("rescued", 0)
    available_rescues = max_rescues - rescued_so_far

    if available_rescues <= 0:
        print(f"  [SUPERVISOR] Rescue budget exhausted ({rescued_so_far}/{max_rescues})")
        return {"rescues_performed": 0, "budget_exhausted": True}

    blocked = get_blocked_tasks(min_age_s=RESCUE_THRESHOLD)
    rescues_performed = 0
    for task in blocked[:available_rescues]:
        print(f"  [RESCUE] Task #{task.get('id')}: {task.get('title','')[:50]}")
        rec = rescue_with_opus(task)
        print(f"  [RESCUE] status={rec.get('status')} quality={rec.get('quality')}/100 "
              f"tokens={rec.get('tokens',0)}")
        rescues_performed += 1

    return {"rescues_performed": rescues_performed, "budget_exhausted": False}


def log_teaching_moment(task: dict, gap_category: str, local_result: dict,
                        opus_result: dict):
    """Log what Claude fixed that local couldn't — for future upgrades."""
    record = {
        "ts": datetime.now().isoformat(),
        "task_id": task.get("id"),
        "title": task.get("title", "")[:80],
        "category": gap_category,
        "local_quality": local_result.get("quality", 0),
        "opus_quality": opus_result.get("quality", 0),
        "quality_gap": opus_result.get("quality", 0) - local_result.get("quality", 0),
        "local_issue": local_result.get("status", "unknown"),
        "teaching": (
            f"Local failed {gap_category}: "
            f"opus scored {opus_result.get('quality',0)} vs local {local_result.get('quality',0)}. "
            f"Lesson: strengthen {gap_category} directives in system prompt."
        ),
    }
    path = os.path.join(REPORTS_DIR, "teaching_moments.jsonl")
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")
    print(f"  [TEACHING] Logged: {record['teaching'][:100]}")


def daemon_loop(version: int, total_tasks: int = 100):
    """Run supervision loop every WATCH_INTERVAL seconds."""
    print(f"[SUPERVISOR] Daemon started for v{version} ({total_tasks} tasks)")
    print(f"[SUPERVISOR] Checking every {WATCH_INTERVAL}s, rescue budget ≤10%")
    while True:
        try:
            supervision_check(version, total_tasks=total_tasks)
        except Exception as e:
            print(f"[SUPERVISOR] Error: {e}")
        time.sleep(WATCH_INTERVAL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", type=int, default=4)
    ap.add_argument("--once", action="store_true", help="Run one check then exit")
    ap.add_argument("--status", action="store_true", help="Print progress and exit")
    ap.add_argument("--tasks", type=int, default=100)
    args = ap.parse_args()

    if args.status:
        progress = get_version_progress(args.version)
        print(json.dumps(progress, indent=2))
        return
    if args.once:
        supervision_check(args.version, total_tasks=args.tasks)
        return
    daemon_loop(args.version, total_tasks=args.tasks)


if __name__ == "__main__":
    main()
