#!/usr/bin/env python3
import json
import os
import pathlib
import subprocess
import sys
from datetime import datetime


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_DIR = REPO_ROOT / "state"
LOG_DIR = REPO_ROOT / "logs"
RUN_LOCK = STATE_DIR / "run.lock"
SESSION_STATE = STATE_DIR / "session-state.json"
PROGRESS_STATE = STATE_DIR / "progress.json"
MENTIONED_FILES = STATE_DIR / "mentioned-files.txt"
REPORT_PATH = LOG_DIR / "runtime-heal-report.md"


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def pid_is_live(pid):
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def load_json(path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def main():
    target_repo = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("LOCAL_AGENT_TARGET_REPO", REPO_ROOT)).resolve()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    actions = []
    warnings = []
    active_pid = 0

    checkpoint = run(["bash", str(REPO_ROOT / "scripts" / "create_checkpoint.sh"), "runtime-heal", str(target_repo)])
    if checkpoint.returncode == 0:
        actions.append(f"Created checkpoint: {checkpoint.stdout.strip().splitlines()[-1]}")
    else:
        warnings.append("Failed to create runtime-heal checkpoint.")

    if RUN_LOCK.exists():
        body = load_json(RUN_LOCK)
        if not body:
            RUN_LOCK.unlink(missing_ok=True)
            actions.append("Removed malformed run.lock file.")
        else:
            active_pid = int(body.get("pid", 0) or 0)
            if pid_is_live(active_pid):
                actions.append(f"Active local run is still live (pid {active_pid}); left lock in place.")
            else:
                RUN_LOCK.unlink(missing_ok=True)
                active_pid = 0
                actions.append("Removed stale run.lock file.")
    else:
        actions.append("No run.lock file was present.")

    session = load_json(SESSION_STATE)
    if session and session.get("status") == "running" and not active_pid:
        idle_state = {
            "status": "idle",
            "task": "",
            "target_repo": str(target_repo),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        write_json(SESSION_STATE, idle_state)
        actions.append("Reset stale session-state.json from running to idle.")

    progress = load_json(PROGRESS_STATE)
    if progress and progress.get("overall", {}).get("status") == "running" and not active_pid:
        progress["overall"]["status"] = "idle"
        progress["current_stage"] = ""
        progress["updated_at"] = datetime.now().isoformat(timespec="seconds")
        write_json(PROGRESS_STATE, progress)
        actions.append("Marked stale progress.json state as idle.")

    if MENTIONED_FILES.exists():
        kept = []
        seen = set()
        for raw in MENTIONED_FILES.read_text().splitlines():
            item = raw.strip()
            if not item:
                continue
            path = pathlib.Path(item)
            if not path.exists():
                continue
            resolved = str(path.resolve())
            if resolved not in seen:
                seen.add(resolved)
                kept.append(resolved)
        MENTIONED_FILES.write_text(("\n".join(kept) + "\n") if kept else "")
        actions.append(f"Normalized mentioned-files list to {len(kept)} live paths.")

    bootstrap = run(["bash", str(REPO_ROOT / "scripts" / "bootstrap_local_runtime.sh")])
    if bootstrap.returncode == 0:
        actions.append("Bootstrapped local runtime.")
    else:
        warnings.append("bootstrap_local_runtime.sh failed during runtime heal.")

    registry = run(["python3", str(REPO_ROOT / "scripts" / "model_registry.py"), "--write"])
    if registry.returncode == 0:
        actions.append("Refreshed local model registry.")
    else:
        warnings.append("model_registry.py --write failed.")

    session_health = run(["python3", str(REPO_ROOT / "scripts" / "session_health.py"), "--heal", "--json"])
    if session_health.returncode == 0:
        try:
            session_data = json.loads(session_health.stdout)
        except json.JSONDecodeError:
            session_data = {}
        duplicate_count = len(session_data.get("duplicates", []))
        heal_count = len(session_data.get("heal_actions", []))
        actions.append(
            f"Checked interactive session health: {duplicate_count} duplicate active session(s), {heal_count} suspended."
        )
    else:
        warnings.append("session_health.py --heal reported warnings.")

    review = run(["python3", str(REPO_ROOT / "scripts" / "review_current_changes.py"), str(target_repo)])
    if review.returncode == 0:
        actions.append("Refreshed current change review artifact.")
    else:
        warnings.append("review_current_changes.py failed.")

    report_lines = [
        "# Runtime Heal Report",
        "",
        f"- generated_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- target_repo: {target_repo}",
        f"- active_run_pid: {active_pid or 'none'}",
        "",
        "## Actions",
    ]
    if actions:
        report_lines.extend(f"- {item}" for item in actions)
    else:
        report_lines.append("- none")
    report_lines.append("")
    report_lines.append("## Warnings")
    if warnings:
        report_lines.extend(f"- {item}" for item in warnings)
    else:
        report_lines.append("- none")
    report_lines.append("")
    report_lines.append("## Artifacts")
    report_lines.append(f"- report: {REPORT_PATH}")
    report_lines.append(f"- review: {REPO_ROOT / 'logs' / 'review-current-changes.md'}")
    report_lines.append(f"- model_registry: {REPO_ROOT / 'state' / 'model-registry.json'}")
    report_lines.append(f"- session_health: {REPO_ROOT / 'logs' / 'session-health-report.md'}")

    REPORT_PATH.write_text("\n".join(report_lines) + "\n")
    print(REPORT_PATH.read_text())
    raise SystemExit(0 if not warnings else 1)


if __name__ == "__main__":
    main()
