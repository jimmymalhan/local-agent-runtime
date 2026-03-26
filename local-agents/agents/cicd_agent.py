"""CI/CD integration -- trigger pipelines, watch builds, auto-fix failures."""
import subprocess
import json
import time
from pathlib import Path


def trigger_workflow(workflow_name: str = None) -> dict:
    """Trigger GitHub Actions workflow"""
    try:
        cmd = ["gh", "workflow", "run", workflow_name or "ci.yml"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {"ok": r.returncode == 0, "output": r.stdout + r.stderr}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_latest_run_status() -> dict:
    """Get status of the most recent CI run"""
    try:
        r = subprocess.run(
            ["gh", "run", "list", "--limit=1", "--json",
             "status,conclusion,name,url,headBranch"],
            capture_output=True, text=True, timeout=30,
        )
        runs = json.loads(r.stdout or "[]")
        return runs[0] if runs else {}
    except Exception as e:
        return {"error": str(e)}


def get_failing_tests(run_id: str = None) -> list:
    """Parse CI failure logs for test names and error messages"""
    try:
        cmd = ["gh", "run", "view", "--log-failed"]
        if run_id:
            cmd.extend([run_id])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        lines = r.stdout.splitlines()
        failures = []
        for line in lines:
            if "FAILED" in line or "Error" in line or "assert" in line.lower():
                failures.append(line.strip()[:200])
            if len(failures) >= 20:
                break
        return failures
    except Exception as e:
        return [str(e)]


def watch_ci(timeout: int = 300, poll_interval: int = 30) -> dict:
    """Poll CI status until done or timeout"""
    start = time.time()
    while time.time() - start < timeout:
        status = get_latest_run_status()
        if status.get("status") in ("completed", "failure", "success"):
            return {"passed": status.get("conclusion") == "success", "run": status}
        time.sleep(poll_interval)
    return {"passed": False, "error": "timeout"}


def run(task: dict) -> dict:
    action = task.get("action", "status")
    if action == "trigger":
        result = trigger_workflow(task.get("workflow"))
    elif action == "watch":
        result = watch_ci(task.get("timeout", 300))
    elif action == "failures":
        result = {"failures": get_failing_tests(task.get("run_id"))}
    else:
        result = get_latest_run_status()
    quality = 80 if result.get("ok") or result.get("passed") else 40
    return {"quality": quality, "output": result, "agent": "cicd_agent"}
