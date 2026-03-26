#!/usr/bin/env python3
"""
git_agent.py — Git and GitHub operations for agents.

Agents call this to: create branches, commit changes, push, create PRs,
monitor CI status, and auto-fix CI failures.

Usage:
    from agents.git_agent import GitAgent
    git = GitAgent(repo_path="/path/to/project")
    git.commit_changes(["file1.py"], "feat: add feature")
    pr_url = git.create_pr("main", "feat: add feature", "Description...")
"""
import os
import sys
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

AGENT_META = {
    "name": "git_agent",
    "version": 1,
    "capabilities": ["git", "github", "branch", "commit", "pr", "ci"],
    "model": "local",
    "input_schema": {
        "action": "str",
        "files":  "list",
        "message": "str",
        "branch": "str",
        "base":   "str",
        "title":  "str",
        "body":   "str",
        "pr_url": "str",
    },
    "output_schema": {
        "status":    "str",
        "output":    "str",
        "quality":   "int",
        "elapsed_s": "float",
    },
    "benchmark_score": None,
}


def _run(cmd, cwd, timeout=60):
    """Run subprocess; return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", f"Timeout after {timeout}s"
    except FileNotFoundError as e:
        return 1, "", f"Not found: {e}"


class GitAgent:
    """Full git + GitHub operations for agents."""

    def __init__(self, repo_path=None):
        self.repo_path = repo_path or os.getcwd()
        self._validate_repo()
        self._has_github = self._detect_github_remote()

    def _validate_repo(self):
        rc, _, _ = _run(["git", "rev-parse", "--git-dir"], self.repo_path)
        if rc != 0:
            raise ValueError(f"Not a git repository: {self.repo_path}")

    def _detect_github_remote(self):
        rc, out, _ = _run(["git", "remote", "-v"], self.repo_path)
        return rc == 0 and "github.com" in out

    def status(self):
        """Returns {branch, modified, untracked, staged, ahead_of_remote, behind_remote}."""
        branch = ""
        rc, out, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], self.repo_path)
        if rc == 0:
            branch = out

        modified, untracked, staged = [], [], []
        rc, out, _ = _run(["git", "status", "--porcelain"], self.repo_path)
        if rc == 0:
            for line in out.splitlines():
                if not line:
                    continue
                xy, name = line[:2], line[3:]
                if xy[0] in ("M", "A", "D", "R", "C"):
                    staged.append(name)
                if xy[1] == "M":
                    modified.append(name)
                elif xy[1] == "?":
                    untracked.append(name)

        ahead, behind = 0, 0
        rc, out, _ = _run(
            ["git", "rev-list", "--count", "--left-right", "@{u}...HEAD"], self.repo_path)
        if rc == 0 and "\t" in out:
            try:
                b, a = out.split("\t")
                behind, ahead = int(b), int(a)
            except (ValueError, IndexError):
                pass

        return {
            "branch": branch, "modified": modified, "untracked": untracked,
            "staged": staged, "ahead_of_remote": ahead, "behind_remote": behind,
        }

    def create_branch(self, name, from_branch="main"):
        """Checkout from_branch then create feature/{name}. Returns branch name."""
        branch_name = f"feature/{name}" if not name.startswith("feature/") else name
        _run(["git", "fetch", "origin", from_branch], self.repo_path, timeout=30)
        rc, _, err = _run(
            ["git", "checkout", "-b", branch_name, f"origin/{from_branch}"], self.repo_path)
        if rc != 0:
            rc2, _, err2 = _run(["git", "checkout", branch_name], self.repo_path)
            if rc2 != 0:
                raise RuntimeError(f"Cannot create/checkout '{branch_name}': {err} | {err2}")
        return branch_name

    def stage_files(self, files):
        """Stage specific files (never git add .). Returns True on success."""
        if not files:
            return False
        safe = [f for f in files if f and not f.startswith("-")]
        if not safe:
            return False
        rc, _, err = _run(["git", "add", "--"] + safe, self.repo_path)
        if rc != 0:
            print(f"[GitAgent] stage error: {err}")
            return False
        return True

    def commit_changes(self, files, message, description=""):
        """Stage files and commit. Returns commit hash or None."""
        if not self.stage_files(files):
            return None
        msg = message.strip()
        if description:
            msg += f"\n\n{description.strip()}"
        msg += "\n\nCo-Authored-By: Nexus Agent <nexus@local>"
        rc, out, err = _run(["git", "commit", "-m", msg], self.repo_path)
        if rc != 0:
            print(f"[GitAgent] commit error: {err}")
            return None
        m = re.search(r"\b([0-9a-f]{7,40})\b", out)
        if m:
            return m.group(1)
        rc2, h, _ = _run(["git", "rev-parse", "HEAD"], self.repo_path)
        return h if rc2 == 0 else None

    def push_branch(self, branch=None):
        """Push branch to origin -u. Returns True on success."""
        if branch is None:
            rc, branch, _ = _run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], self.repo_path)
            if rc != 0:
                return False
        rc, _, err = _run(["git", "push", "-u", "origin", branch], self.repo_path, timeout=60)
        if rc != 0:
            print(f"[GitAgent] push error: {err}")
            return False
        return True

    def create_pr(self, base, title, body, draft=False):
        """Create GitHub PR via gh CLI. Returns PR URL or empty string."""
        if not self._has_github:
            print("[GitAgent] No GitHub remote — skipping PR")
            return ""
        cmd = ["gh", "pr", "create", "--base", base, "--title", title, "--body", body]
        if draft:
            cmd.append("--draft")
        rc, out, err = _run(cmd, self.repo_path, timeout=60)
        if rc != 0:
            print(f"[GitAgent] create_pr error: {err}")
            return ""
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        return lines[-1] if lines else ""

    def get_pr_status(self, pr_url):
        """Returns {state, ci_passing, review_status, checks: list}."""
        if not pr_url:
            return {"state": "unknown", "ci_passing": False,
                    "review_status": "none", "checks": []}
        rc, out, err = _run(
            ["gh", "pr", "view", pr_url, "--json",
             "state,statusCheckRollup,reviews,mergeable"],
            self.repo_path, timeout=30,
        )
        if rc != 0:
            return {"state": "unknown", "ci_passing": False,
                    "review_status": "none", "checks": []}
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return {"state": "unknown", "ci_passing": False,
                    "review_status": "none", "checks": []}

        checks = data.get("statusCheckRollup", []) or []
        check_list = [
            {"name": c.get("name", c.get("context", "")),
             "status": c.get("status", ""),
             "conclusion": c.get("conclusion", c.get("state", ""))}
            for c in checks
        ]
        ok = {"SUCCESS", "NEUTRAL", "SKIPPED"}
        ci_passing = bool(check_list) and all(
            c["conclusion"].upper() in ok for c in check_list if c["conclusion"]
        )
        reviews = data.get("reviews", []) or []
        approved = any(r.get("state") == "APPROVED" for r in reviews)
        changes  = any(r.get("state") == "CHANGES_REQUESTED" for r in reviews)
        review_status = (
            "approved" if approved else "changes_requested" if changes else "pending"
        )
        return {
            "state": data.get("state", "unknown"), "ci_passing": ci_passing,
            "review_status": review_status, "checks": check_list,
            "mergeable": data.get("mergeable", "UNKNOWN"),
        }

    def watch_ci(self, pr_url, timeout=300):
        """Poll CI every 30s. Returns {passed, failed_jobs, duration}."""
        interval, start = 30, time.time()
        failed_jobs = []
        while True:
            elapsed = int(time.time() - start)
            pr_status = self.get_pr_status(pr_url)
            checks = pr_status.get("checks", [])
            pending = [
                c for c in checks
                if c.get("status", "").upper() not in
                ("COMPLETED", "SUCCESS", "FAILURE", "CANCELLED", "TIMED_OUT")
            ]
            failed_jobs = [
                c for c in checks
                if c.get("conclusion", "").upper() in ("FAILURE", "CANCELLED", "TIMED_OUT")
            ]
            if not pending:
                return {"passed": bool(checks) and not failed_jobs,
                        "failed_jobs": failed_jobs, "duration": elapsed}
            if elapsed >= timeout:
                return {"passed": False, "failed_jobs": failed_jobs + pending,
                        "duration": elapsed, "timed_out": True}
            print(f"[GitAgent] CI: {len(pending)} pending "
                  f"({elapsed}s/{timeout}s) — retry in {interval}s")
            time.sleep(interval)

    def get_failing_tests(self, pr_url):
        """Parse CI failure logs. Returns [{test_name, error_message, file, line}]."""
        if not pr_url:
            return []
        rc, out, _ = _run(
            ["gh", "pr", "checks", pr_url, "--json", "name,link,state"],
            self.repo_path, timeout=30)
        failing = []
        if rc != 0:
            return failing
        try:
            checks = json.loads(out)
        except json.JSONDecodeError:
            return failing
        for check in checks:
            if check.get("state", "").upper() not in ("FAILURE", "FAIL"):
                continue
            link = check.get("link", "")
            m = re.search(r"/runs/(\d+)", link)
            if not m:
                continue
            run_id = m.group(1)
            rc2, log_out, _ = _run(
                ["gh", "run", "view", run_id, "--log-failed"],
                self.repo_path, timeout=60)
            if rc2 != 0:
                continue
            for log_line in log_out.splitlines():
                tm = re.search(
                    r"(FAIL(?:ED)?)\s+([\w/.\-]+(?:\.test\.[jt]sx?|\.spec\.[jt]sx?|\.py))"
                    r"(?:\s+>?\s*(.+))?",
                    log_line,
                )
                if tm:
                    file_ = tm.group(2)
                    tname = (tm.group(3) or "").strip()
                    failing.append({
                        "test_name": tname or file_,
                        "error_message": log_line.strip(),
                        "file": file_,
                        "line": "",
                    })
                    continue
                em = re.search(r"(Error|Exception|assert).*?:\s+(.+)", log_line)
                if em and failing:
                    failing[-1]["error_message"] = log_line.strip()
        return failing

    def auto_commit_after_task(self, task, result):
        """
        Called after a successful task (quality >= 70).
        Creates branch, stages files_written, commits. Returns hash or None.
        """
        quality = result.get("quality", 0)
        if quality < 70:
            return None
        task_id  = task.get("id", "unknown")
        category = re.sub(r"[^a-z0-9_-]", "", task.get("category", "task").lower())
        title    = task.get("title", f"task-{task_id}")
        branch_name = f"feature/{category}-{task_id}"
        files_written = result.get("files_written", [])
        if not files_written:
            st = self.status()
            files_written = list(set(st["modified"] + st["untracked"] + st["staged"]))
        if not files_written:
            return None
        try:
            try:
                self.create_branch(branch_name)
            except RuntimeError:
                pass  # Already on a suitable branch
            h = self.commit_changes(
                files=files_written,
                message=f"feat({category}): {title}",
                description=f"Task #{task_id} — auto-committed after quality={quality}/100",
            )
            if h:
                print(f"[GitAgent] auto_commit task={task_id} "
                      f"quality={quality} branch={branch_name} hash={h}")
            return h
        except Exception as exc:
            print(f"[GitAgent] auto_commit_after_task error: {exc}")
            return None

    def run_action(self, task):
        """Route by task['action']: commit | pr | status | watch_ci."""
        start  = time.time()
        action = task.get("action", "status")
        try:
            if action == "status":
                return {
                    "status": "done", "output": json.dumps(self.status()),
                    "quality": 100, "elapsed_s": round(time.time() - start, 2),
                }
            elif action == "commit":
                h = self.commit_changes(
                    task.get("files", []),
                    task.get("message", "chore: agent commit"),
                    task.get("description", ""),
                )
                if h:
                    return {"status": "done", "output": h, "quality": 90,
                            "elapsed_s": round(time.time() - start, 2)}
                return {"status": "failed",
                        "output": "nothing staged or commit failed",
                        "quality": 0, "elapsed_s": round(time.time() - start, 2)}
            elif action == "pr":
                url = self.create_pr(
                    task.get("base", "main"), task.get("title", "Agent PR"),
                    task.get("body", ""), task.get("draft", False),
                )
                if url:
                    return {"status": "done", "output": url, "quality": 90,
                            "elapsed_s": round(time.time() - start, 2)}
                return {"status": "failed", "output": "PR creation failed — check gh auth",
                        "quality": 0, "elapsed_s": round(time.time() - start, 2)}
            elif action == "watch_ci":
                res = self.watch_ci(
                    task.get("pr_url", ""), int(task.get("timeout", 300)))
                return {
                    "status": "done" if res.get("passed") else "failed",
                    "output": json.dumps(res),
                    "quality": 100 if res.get("passed") else 0,
                    "elapsed_s": round(time.time() - start, 2),
                }
            else:
                return {
                    "status": "failed",
                    "output": (f"Unknown action '{action}'. "
                               "Use: commit | pr | status | watch_ci"),
                    "quality": 0, "elapsed_s": round(time.time() - start, 2),
                }
        except Exception as exc:
            return {"status": "failed", "output": str(exc), "quality": 0,
                    "elapsed_s": round(time.time() - start, 2)}


def run(task):
    """Standard agent entry point. task['action'] selects operation."""
    repo_path = task.get("repo_path") or BASE_DIR
    try:
        agent = GitAgent(repo_path=repo_path)
    except ValueError as exc:
        return {"status": "failed", "output": str(exc), "quality": 0,
                "elapsed_s": 0.0, "agent": "git_agent"}
    result = agent.run_action(task)
    result["agent"] = "git_agent"
    return result
