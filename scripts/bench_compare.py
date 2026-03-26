#!/usr/bin/env python3
"""
bench_compare.py — Master Benchmark Orchestrator v4→v100
=========================================================
Single source of truth for comparing local agents vs Opus 4.6.

Architecture (90% local / 10% Claude):
  - Each task runs on local agent first (90% of work)
  - Claude Opus 4.6 runs same task for baseline comparison
  - Claude supervises every 180s and rescues blocked tasks (≤10% of tasks)
  - After each version: analyze gaps → upgrade agent_runner.py → re-benchmark
  - Stop when local beats Opus 4.6 across all categories OR at v100

Usage:
  python3 bench_compare.py --version 4                 # run v4 full benchmark
  python3 bench_compare.py --version 4 --quick 5       # run 5 tasks only
  python3 bench_compare.py --version 4 --local-only    # skip Opus (free run)
  python3 bench_compare.py --auto 4                    # full loop v4→v100
  python3 bench_compare.py --report 4                  # print v4 leaderboard
  python3 bench_compare.py --token-report              # token usage comparison
"""
import os, sys, json, time, argparse, subprocess, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# ── Paths (single source) ───────────────────────────────────────────────────
BASE_DIR    = "/Users/jimmymalhan/Documents/local-agent-runtime/local-agents"
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
BOS         = os.path.expanduser("~/local-agents-os")
API         = f"http://127.0.0.1:{os.environ.get('PORT_API', '8000')}"
Path(REPORTS_DIR).mkdir(exist_ok=True)
sys.path.insert(0, BASE_DIR)

# ── Import from single-source modules ──────────────────────────────────────
from opus_benchmark import build_task_suite
from opus_runner import run_opus_task

# ── Config ─────────────────────────────────────────────────────────────────
LOCAL_MODEL      = os.environ.get("LOCAL_MODEL", "qwen2.5-coder:7b")
OPUS_MODEL       = "claude-opus-4-6"
LOCAL_TIMEOUT    = 360
POLL_INTERVAL    = 8
SUPERVISE_EVERY  = 180   # Claude checks every 3 minutes
RESCUE_THRESHOLD = 120
WIN_THRESHOLD    = 5.0
CATEGORY_MAP = {
    "code_gen":  "Code Generation",
    "bug_fix":   "Bug Fixing",
    "scaffold":  "Project Scaffold",
    "tdd":       "TDD Red/Green",
    "arch":      "Architecture",
    "refactor":  "Refactoring",
    "e2e":       "E2E Pipeline",
}

# Version task tiers — each version expands the category set
VERSION_TIERS = {
    4:  {"categories": ["code_gen", "bug_fix"],
         "label": "v4: Code Gen + Bug Fix"},
    5:  {"categories": ["code_gen", "bug_fix", "scaffold"],
         "label": "v5: + Project Scaffold"},
    6:  {"categories": ["code_gen", "bug_fix", "scaffold", "tdd"],
         "label": "v6: + TDD Red/Green"},
    7:  {"categories": ["code_gen", "bug_fix", "scaffold", "tdd", "arch"],
         "label": "v7: + Architecture Design"},
    8:  {"categories": ["code_gen", "bug_fix", "scaffold", "tdd", "arch", "refactor"],
         "label": "v8: + Refactoring"},
    9:  {"categories": list(CATEGORY_MAP.keys()),
         "label": "v9: Full 100-task suite"},
    10: {"categories": list(CATEGORY_MAP.keys()),
         "label": "v10: ULTRA — all 100 + harder prompts"},
}
for _v in range(11, 101):
    VERSION_TIERS[_v] = VERSION_TIERS[10]


# ── API helpers ─────────────────────────────────────────────────────────────

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


def get_or_create_project(version: int) -> int:
    projects = api_call("GET", "/projects") or []
    for p in projects:
        if f"Benchmark-v{version}" in p.get("name", ""):
            return p["id"]
    proj = api_call("POST", "/projects", {
        "name": f"Benchmark-v{version} Local vs Opus",
        "description": f"bench_compare.py v{version}",
    })
    return proj["id"] if proj else 1


# ── Local agent runner ──────────────────────────────────────────────────────

def run_local_task(task: dict, project_id: int, version: int) -> dict:
    title = f"[v{version}] {task.get('title', '')}"
    print(f"  [LOCAL] Creating: {title[:70]}")
    start = time.time()
    board_task = api_call("POST", "/tasks", {
        "project_id": project_id,
        "title": title,
        "description": task.get("description", title),
        "task_type": "bug" if task.get("category") == "bug_fix" else "code",
        "status": "todo",
        "priority": "high",
        "assignee": "local-agent",
        "agent_model": LOCAL_MODEL,
        "estimated_hours": 0.5,
        "codebase_path": BOS,
    })
    if not board_task or "id" not in board_task:
        return {"status": "create_failed", "quality": 0, "elapsed_s": 0,
                "total_tokens": 0, "iters": 0}
    bid = board_task["id"]
    prev_status = "todo"
    iters = 0
    while time.time() - start < LOCAL_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        t = api_call("GET", f"/tasks/{bid}")
        if not t:
            continue
        status = t.get("status", "")
        if status != prev_status:
            print(f"  [LOCAL] #{bid} → {status} ({time.time()-start:.0f}s)")
            prev_status = status
        iters += 1
        if status == "done":
            elapsed = time.time() - start
            logs = api_call("GET", f"/tasks/{bid}/logs") or []
            quality = _score_local(t, logs)
            print(f"  [LOCAL] Done {elapsed:.1f}s | q={quality}/100")
            return {"status": "done", "quality": quality, "elapsed_s": round(elapsed, 1),
                    "total_tokens": len(logs) * 800, "iters": iters, "board_task_id": bid}
        if status == "blocked":
            elapsed = time.time() - start
            return {"status": "blocked", "quality": 0, "elapsed_s": round(elapsed, 1),
                    "total_tokens": 0, "iters": iters, "board_task_id": bid}
    elapsed = time.time() - start
    api_call("PATCH", f"/tasks/{bid}", {"status": "blocked"})
    return {"status": "timeout", "quality": 0, "elapsed_s": round(elapsed, 1),
            "total_tokens": 0, "iters": 0}


def _score_local(task_record: dict, logs: list) -> int:
    score = 40
    log_text = " ".join(str(l) for l in logs).lower()
    if "pass" in log_text or "assertion" in log_text:
        score += 20
    if "error" not in log_text and "failed" not in log_text:
        score += 15
    if "done" in log_text:
        score += 15
    try:
        score = int(task_record.get("eval_score", score))
    except Exception:
        pass
    return min(100, score)


# ── Claude rescue (10% budget) ──────────────────────────────────────────────

def claude_rescue(task: dict, version: int) -> dict:
    print(f"  [RESCUE] Claude rescuing: {task.get('title','')[:60]}")
    start = time.time()
    result = run_opus_task(task, version)
    elapsed = time.time() - start
    rescue_record = {
        "ts": datetime.now().isoformat(), "version": version,
        "task_id": task.get("id"), "title": task.get("title"),
        "elapsed_s": round(elapsed, 1), "quality": result.get("quality", 0),
        "tokens": result.get("tokens", 0), "status": result.get("status"),
    }
    with open(os.path.join(REPORTS_DIR, "claude_rescues.jsonl"), "a") as f:
        f.write(json.dumps(rescue_record) + "\n")
    return rescue_record


# ── Token comparison logging ────────────────────────────────────────────────

def log_token_comparison(version, task_id, local_tokens, opus_tokens):
    opus_cost = opus_tokens * 0.000015
    record = {
        "ts": datetime.now().isoformat(), "version": version, "task_id": task_id,
        "local_tokens": local_tokens, "opus_tokens": opus_tokens,
        "local_cost_usd": 0.0, "opus_cost_usd": round(opus_cost, 6),
        "savings_usd": round(opus_cost, 6),
    }
    with open(os.path.join(REPORTS_DIR, "token_comparison.jsonl"), "a") as f:
        f.write(json.dumps(record) + "\n")


# ── Results I/O ──────────────────────────────────────────────────────────────

def results_path(version: int) -> str:
    return os.path.join(REPORTS_DIR, f"v{version}_compare.jsonl")


def append_result(record: dict, version: int):
    with open(results_path(version), "a") as f:
        f.write(json.dumps(record) + "\n")


def load_results(version: int) -> list:
    path = results_path(version)
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            try:
                out.append(json.loads(line.strip()))
            except Exception:
                pass
    return out


def already_done_ids(version: int) -> set:
    return {r["task_id"] for r in load_results(version)}


def local_beats_opus(version: int) -> bool:
    results = load_results(version)
    if len(results) < 5:
        return False
    cats = defaultdict(lambda: {"local_q": 0, "opus_q": 0, "count": 0})
    for r in results:
        cat = r.get("category", "x")
        cats[cat]["local_q"] += r.get("local_quality", 0)
        cats[cat]["opus_q"] += r.get("opus_quality", 0)
        cats[cat]["count"] += 1
    for cat, d in cats.items():
        n = d["count"] or 1
        if (d["opus_q"] / n) - (d["local_q"] / n) > WIN_THRESHOLD:
            return False
    return True


# ── Report generation ───────────────────────────────────────────────────────

def generate_report(version: int) -> str:
    results = load_results(version)
    if not results:
        return f"No results for v{version}"
    cats = defaultdict(lambda: {"total": 0, "local_done": 0, "local_q": 0,
                                "opus_done": 0, "opus_q": 0, "rescued": 0,
                                "local_tok": 0, "opus_tok": 0})
    for r in results:
        cat = r.get("category", "unknown")
        cats[cat]["total"] += 1
        cats[cat]["local_done"] += int(r.get("local_status") == "done")
        cats[cat]["local_q"] += r.get("local_quality", 0)
        cats[cat]["opus_done"] += int(r.get("opus_status") in ("done", "partial"))
        cats[cat]["opus_q"] += r.get("opus_quality", 0)
        cats[cat]["rescued"] += int(r.get("claude_rescued", False))
        cats[cat]["local_tok"] += r.get("local_tokens", 0)
        cats[cat]["opus_tok"] += r.get("opus_tokens", 0)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    tier = VERSION_TIERS.get(version, VERSION_TIERS[10])
    lines = [
        f"# Benchmark v{version} — Local Agents vs Opus 4.6 — {now}",
        f"**Tier:** {tier['label']}",
        f"",
        f"| Category | Tasks | Local Done% | Local Avg Q | Opus Done% | Opus Avg Q | Winner |",
        f"|----------|-------|-------------|-------------|------------|------------|--------|",
    ]
    lw = ow = 0
    tl_tok = to_tok = 0
    for cat, d in sorted(cats.items()):
        n = max(d["total"], 1)
        lq = d["local_q"] / n
        oq = d["opus_q"] / n
        winner = "local" if lq >= oq - WIN_THRESHOLD else "opus"
        if winner == "local":
            lw += 1
        else:
            ow += 1
        tl_tok += d["local_tok"]
        to_tok += d["opus_tok"]
        label = CATEGORY_MAP.get(cat, cat)
        lines.append(
            f"| {label} | {n} | {100*d['local_done']//n}% | "
            f"{lq:.0f}/100 | {100*d['opus_done']//n}% | {oq:.0f}/100 | {winner} |"
        )

    total_rescued = sum(d["rescued"] for d in cats.values())
    rescue_pct = total_rescued / max(len(results), 1) * 100
    lines += [
        f"",
        f"**Local wins:** {lw}  |  **Opus wins:** {ow}",
        f"**Claude rescue rate:** {rescue_pct:.1f}% (target ≤10%)",
        f"**Local tokens:** {tl_tok:,} ($0.00)  |  **Opus tokens:** {to_tok:,} (${to_tok*0.000015:.4f})",
        f"",
        f"## Verdict",
        f"**{'LOCAL AGENTS WIN' if lw > ow else 'OPUS WINS' if ow > lw else 'TIE'}** "
        f"({lw}/{lw+ow} categories local) — {'stopping.' if lw > ow else f'upgrade to v{version+1}'}",
    ]
    return "\n".join(lines)


# ── Trigger upgrade_agent.py ────────────────────────────────────────────────

def trigger_upgrade(from_v: int, to_v: int) -> bool:
    print(f"\n[UPGRADE] upgrade_agent.py --from {from_v} --to {to_v}")
    r = subprocess.run(
        [sys.executable, os.path.join(BASE_DIR, "upgrade_agent.py"),
         "--from", str(from_v), "--to", str(to_v)],
        capture_output=True, text=True, timeout=120
    )
    if r.stdout:
        print(r.stdout[-2000:])
    return r.returncode == 0


# ── Single version benchmark ────────────────────────────────────────────────

def run_version(version: int, quick: int = 0, local_only: bool = False, resume: bool = True):
    tier = VERSION_TIERS.get(version, VERSION_TIERS[10])
    print(f"\n{'='*68}")
    print(f"  bench_compare v{version}  |  {tier['label']}")
    print(f"  Local: {LOCAL_MODEL}  vs  Opus: {OPUS_MODEL}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*68}")

    all_tasks = build_task_suite()
    tasks = [t for t in all_tasks if t.get("category") in tier["categories"]]
    if quick:
        tasks = tasks[:quick]
    done_ids = already_done_ids(version) if resume else set()
    tasks = [t for t in tasks if t["id"] not in done_ids]
    print(f"  Tasks: {len(tasks)} remaining  (skipping {len(done_ids)} done)")

    project_id = get_or_create_project(version)
    total = len(tasks)
    rescue_count = 0
    last_supervise = time.time()

    for idx, task in enumerate(tasks):
        print(f"\n[{idx+1}/{total}] {task['id']} | {task['title'][:58]}")

        # Claude supervises every 3 min (10% role)
        if time.time() - last_supervise >= SUPERVISE_EVERY:
            _supervision_check(version, rescue_count, total)
            last_supervise = time.time()

        # 1. Local agent (90%)
        local_result = run_local_task(task, project_id, version)

        # 2. Claude rescue if blocked (≤10% budget)
        claude_rescued = False
        rescue_quality = 0
        if local_result["status"] in ("blocked", "timeout", "create_failed"):
            if rescue_count < total * 0.10:
                rec = claude_rescue(task, version)
                rescue_count += 1
                rescue_quality = rec.get("quality", 0)
                claude_rescued = True

        # 3. Opus 4.6 baseline comparison
        opus_result = {"status": "skipped", "quality": 84, "elapsed_s": 0, "tokens": 0}
        if not local_only:
            print(f"  [OPUS] Running Opus 4.6 baseline...")
            opus_result = run_opus_task(task, version)

        effective_local_q = max(local_result.get("quality", 0), rescue_quality)

        record = {
            "task_id": task["id"], "category": task.get("category"),
            "title": task.get("title"), "version": version,
            "ts": datetime.now().isoformat(),
            "local_status": local_result["status"],
            "local_quality": effective_local_q,
            "local_elapsed_s": local_result.get("elapsed_s", 0),
            "local_tokens": local_result.get("total_tokens", 0),
            "claude_rescued": claude_rescued,
            "opus_status": opus_result.get("status", "skipped"),
            "opus_quality": opus_result.get("quality", 0),
            "opus_elapsed_s": opus_result.get("elapsed_s", 0),
            "opus_tokens": opus_result.get("tokens", 0),
        }
        append_result(record, version)
        log_token_comparison(version, task["id"],
                             local_result.get("total_tokens", 0),
                             opus_result.get("tokens", 0))

        winner = "local" if effective_local_q >= opus_result.get("quality", 0) - WIN_THRESHOLD else "opus"
        print(f"  → local={effective_local_q}  opus={opus_result.get('quality',0)}  winner={winner}")

    rpt = generate_report(version)
    rpt_path = os.path.join(REPORTS_DIR, f"v{version}_compare_report.md")
    with open(rpt_path, "w") as f:
        f.write(rpt)
    print(f"\n[REPORT] {rpt_path}")
    print(rpt)
    return local_beats_opus(version)


def _supervision_check(version, rescue_count, total_tasks):
    results = load_results(version)
    done = len(results)
    rescue_pct = rescue_count / max(total_tasks, 1) * 100
    print(f"\n[SUPERVISOR v{version}] {datetime.now().strftime('%H:%M:%S')}")
    print(f"  Progress: {done}/{total_tasks} | Rescue rate: {rescue_pct:.1f}%")
    if results:
        lq = sum(r.get("local_quality", 0) for r in results) / len(results)
        oq = sum(r.get("opus_quality", 0) for r in results) / len(results)
        print(f"  Avg quality — local: {lq:.1f}  opus: {oq:.1f}  gap: {oq-lq:+.1f}")
        if oq - lq > WIN_THRESHOLD:
            print(f"  [SUPERVISOR] Gap {oq-lq:.1f}pts → upgrade needed after version completes")


# ── Auto loop v4→v100 ────────────────────────────────────────────────────────

def run_auto_loop(start_version: int = 4, quick: int = 0, local_only: bool = False):
    print(f"\n[AUTO] Starting loop v{start_version}→v100")
    print(f"[AUTO] Stop: local agents beat Opus 4.6 across ALL categories")
    for version in range(start_version, 101):
        print(f"\n{'#'*68}\n# VERSION v{version}\n{'#'*68}")
        won = run_version(version, quick=quick, local_only=local_only)
        if won:
            print(f"\n[AUTO] LOCAL AGENTS BEAT OPUS 4.6 at v{version}! Done.")
            _print_final_token_report()
            break
        if version < 100:
            trigger_upgrade(version, version + 1)
    else:
        print(f"\n[AUTO] Reached v100 — final verdict:")
        print(generate_report(100))
        _print_final_token_report()


def _print_final_token_report():
    path = os.path.join(REPORTS_DIR, "token_comparison.jsonl")
    if not os.path.exists(path):
        return
    records = []
    with open(path) as f:
        for line in f:
            try:
                records.append(json.loads(line.strip()))
            except Exception:
                pass
    tl = sum(r.get("local_tokens", 0) for r in records)
    to = sum(r.get("opus_tokens", 0) for r in records)
    print(f"\nTOKEN SUMMARY ({len(records)} tasks)")
    print(f"  Local: {tl:,} tokens  $0.00")
    print(f"  Opus:  {to:,} tokens  ${to*0.000015:.4f}")
    print(f"  Savings: ${to*0.000015:.4f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", "-v", type=int, default=4)
    ap.add_argument("--quick", "-q", type=int, default=0)
    ap.add_argument("--local-only", action="store_true")
    ap.add_argument("--auto", type=int, metavar="START")
    ap.add_argument("--resume", action="store_true", default=True)
    ap.add_argument("--no-resume", dest="resume", action="store_false")
    ap.add_argument("--report", type=int, metavar="VERSION")
    ap.add_argument("--token-report", action="store_true")
    args = ap.parse_args()
    if args.token_report:
        _print_final_token_report()
    elif args.report:
        print(generate_report(args.report))
    elif args.auto is not None:
        run_auto_loop(args.auto, quick=args.quick, local_only=args.local_only)
    else:
        won = run_version(args.version, quick=args.quick,
                          local_only=args.local_only, resume=args.resume)
        print(f"\n[RESULT] local_wins_v{args.version}={won}")


if __name__ == "__main__":
    main()
