#!/usr/bin/env python3
"""
opus_runner.py — Claude CLI Wrapper (NO Anthropic API)
=======================================================
Runs benchmark tasks through `claude -p "..." --model claude-opus-4-6`
exactly like a real power user. Tests real rate limits, real UX, real quality.

Key behaviors:
  - Uses `claude -p` (print mode) — non-interactive, script-friendly
  - Captures stdout/stderr + wall-clock time
  - Parses output for quality signals (assertions pass, code written, etc.)
  - Handles rate limits with exponential backoff
  - Tracks estimated tokens (chars / 4)
  - Logs to reports/opus_raw_v{N}.jsonl

Usage (standalone test):
  python3 opus_runner.py --task-id codegen_01 --version 4
"""
import os, sys, json, time, subprocess, re, argparse
from datetime import datetime
from pathlib import Path

BASE_DIR    = "/Users/jimmymalhan/Documents/local-agent-runtime/local-agents"
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
Path(REPORTS_DIR).mkdir(exist_ok=True)

OPUS_MODEL      = "claude-opus-4-6"
RETRY_MAX       = 3
RETRY_BACKOFF   = [30, 60, 120]   # seconds between retries on rate limit
TASK_TIMEOUT    = 300             # 5 min per task max

RATE_LIMIT_SIGNALS = [
    "rate limit", "too many requests", "overloaded",
    "529", "429", "quota", "usage limit", "try again"
]


def estimate_tokens(text: str) -> int:
    """Rough token estimate: chars / 4."""
    return max(1, len(text) // 4)


def is_rate_limited(output: str) -> bool:
    text = output.lower()
    return any(sig in text for sig in RATE_LIMIT_SIGNALS)


def score_opus_output(task: dict, stdout: str, stderr: str, returncode: int) -> int:
    """Score Opus output 0-100 based on quality signals."""
    score = 0
    if returncode == 0:
        score += 20
    text = (stdout + stderr).lower()

    # Code was written
    if "def " in stdout or "class " in stdout:
        score += 15
    # Assertions or tests mentioned
    if "assert" in stdout or "pass" in text:
        score += 15
    # No errors
    if "error" not in text and "traceback" not in text:
        score += 15
    # Task completed indicator
    if "done" in text or "complete" in text or "written" in text:
        score += 20
    # Long, detailed response (not a cop-out)
    if len(stdout) > 500:
        score += 10
    # No rate limit or refusal
    if is_rate_limited(stdout + stderr):
        score = max(0, score - 30)
    if "i cannot" in text or "i'm sorry" in text or "i can't" in text:
        score = max(0, score - 20)

    return min(100, score)


def summarize_by_category(results: list) -> dict:
    """Summarize opus results by category. Called by bench_runner_v4.py."""
    from collections import defaultdict
    summary = defaultdict(lambda: {"count": 0, "quality": 0, "done": 0, "tokens": 0})
    for r in results:
        cat = r.get("category", "unknown")
        summary[cat]["count"] += 1
        summary[cat]["quality"] += r.get("quality", 0)
        summary[cat]["done"] += int(r.get("status") in ("done", "partial"))
        summary[cat]["tokens"] += r.get("tokens", 0)
    return dict(summary)


def run_opus_task(task: dict, version: int) -> dict:
    """
    Run a single task through the Claude CLI with opus-4-6 model.
    Returns: {status, quality, elapsed_s, tokens, stdout, stderr}
    """
    task_id = task.get("id", "unknown")
    title = task.get("title", "")
    description = task.get("description", title)

    prompt = (
        f"You are an expert software engineer. Complete this coding task fully.\n\n"
        f"TASK: {title}\n\n"
        f"INSTRUCTIONS:\n{description}\n\n"
        f"Requirements:\n"
        f"- Write complete, working Python code (not pseudocode or snippets)\n"
        f"- Include all required imports\n"
        f"- Add a __main__ block with assertions that verify correctness\n"
        f"- Do NOT truncate — complete the full implementation\n"
        f"- Do NOT explain, just write the code\n"
    )

    raw_log_path = os.path.join(REPORTS_DIR, f"opus_raw_v{version}.jsonl")
    start = time.time()

    for attempt in range(RETRY_MAX):
        try:
            result = subprocess.run(
                ["claude", "-p", prompt, "--model", OPUS_MODEL],
                capture_output=True, text=True, timeout=TASK_TIMEOUT
            )
            elapsed = time.time() - start
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            combined = stdout + stderr

            # Check for rate limit
            if is_rate_limited(combined) and attempt < RETRY_MAX - 1:
                wait = RETRY_BACKOFF[attempt]
                print(f"  [OPUS] Rate limited — waiting {wait}s before retry {attempt+1}")
                time.sleep(wait)
                continue

            tokens = estimate_tokens(combined)
            quality = score_opus_output(task, stdout, stderr, result.returncode)
            status = "done" if result.returncode == 0 and quality >= 40 else "partial"

            record = {
                "ts": datetime.now().isoformat(),
                "task_id": task_id,
                "category": task.get("category"),
                "title": title,
                "version": version,
                "status": status,
                "quality": quality,
                "elapsed_s": round(elapsed, 1),
                "tokens": tokens,
                "returncode": result.returncode,
                "attempt": attempt + 1,
            }
            with open(raw_log_path, "a") as f:
                f.write(json.dumps(record) + "\n")
            return record

        except subprocess.TimeoutExpired:
            elapsed = time.time() - start
            print(f"  [OPUS] Timeout after {elapsed:.0f}s")
            return {
                "status": "timeout", "quality": 0, "elapsed_s": round(elapsed, 1),
                "tokens": 0, "task_id": task_id, "attempt": attempt + 1,
            }
        except FileNotFoundError:
            print(f"  [OPUS] 'claude' CLI not found — install Claude Code CLI")
            return {"status": "no_cli", "quality": 0, "elapsed_s": 0, "tokens": 0}
        except Exception as e:
            print(f"  [OPUS] Error: {e}")
            return {"status": "error", "quality": 0, "elapsed_s": 0, "tokens": 0}

    return {"status": "rate_limit_exhausted", "quality": 0, "elapsed_s": 0, "tokens": 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", default="codegen_01")
    ap.add_argument("--version", type=int, default=4)
    args = ap.parse_args()
    sys.path.insert(0, BASE_DIR)
    from opus_benchmark import build_task_suite
    tasks = {t["id"]: t for t in build_task_suite()}
    task = tasks.get(args.task_id)
    if not task:
        print(f"Task {args.task_id} not found")
        return
    result = run_opus_task(task, args.version)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
