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
        "action": "str",   # commit | pr | status | watch_ci
        "files":   "list",
        "message": "str",
        "branch":  "str",
        "base":    "str",
        "title":   "str",
        "body":    "str",
        "pr_url":  "str",
    },
    "output_schema": {
        "status":    "str",    # done | failed
        "output":    "str",
        "quality":   "int",    # 0-100
        "elapsed_s": "float",
    },
    "benchmark_score": None,
}


def _run(cmd: list, cwd: str, timeout: int = 60) -> tuple[int, str, str]:
    """Run a subprocess command; return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", f"Command timed out after {timeout}s: {' '.join(cmd)}"
    except FileNotFoundError as e:
        return 1, "", f"Command not found: {e}"


class GitAgent:
    """
    Full git + GitHub operations for agents.

    All write operations (branch, commit, push, PR) are explicit — never
    implicit side-effects. Auto-commit is only invoked when quality >= 70.
    """

    def __init__(self, repo_path: str = None):
        self.repo_path = repo_path or os.getcwd()
        self._validate_repo()
        self._has_github = self._detect_github_remote()

    # ── Validation ────────────────────────────────────────────────────────

    def _validate_repo(self):
        rc, _, _ = _run(["git", "rev-parse", "--git-dir"], self.repo_path)
        if rc != 0:
            raise ValueError(f"Not a git repository: {self.repo_path}")

    def _detect_github_remote(self) -> bool:
        rc, out, _ = _run(["git", "remote", "-v"], self.repo_path)
        if rc != 0:
            return False
        return "github.com" in out

    # ── Status ────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """
        Returns current repo state:
        {branch, modified, untracked, staged, ahead_of_remote, behind_remote}
        """
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
            ["git", "rev-list", "--count", "--left-right", "@{u}...HEAD"],
            self.repo_path,
        )
        if rc == 0 and "\t" in out:
            parts = out.split("\t")
            try:
                behind = int(parts[0])
                ahead  = int(parts[1])
            except (ValueError, IndexError):
                pass

        return {
            "branch":           branch,
            "modified":         modified,
            "untracked":        untracked,
            "staged":           staged,
            "ahead_of_remote":  ahead,
            "behind_remote":    behind,
        }

    # ── Branch ────────────────────────────────────────────────────────────

    def create_branch(self, name: str, from_branch: str = "main") -> str:
        """
        Checkout from_branch then create feature/{name}.
        Returns the full branch name.
        """
        branch_name = f"feature/{name}" if not name.startswith("feature/") else name

        # Fetch latest so we branch from up-to-date base
        _run(["git", "fetch", "origin", from_branch], self.repo_path, timeout=30)

        rc, _, err = _run(
            ["git", "checkout", "-b", branch_name, f"origin/{from_branch}"],
            self.repo_path,
        )
        if rc != 0:
            # Branch may already exist locally — try plain checkout
            rc2, _, err2 = _run(["git", "checkout", branch_name], self.repo_path)
            if rc2 != 0:
                raise RuntimeError(
                    f"Could not create/checkout branch '{branch_name}': {err} | {err2}"
                )
        return branch_name

    # ── Staging ───────────────────────────────────────────────────────────

    def stage_files(self, files: list) -> bool:
        """
        Stage specific files (never `git add .` to avoid accidental secrets).
        Returns True if all files staged successfully.
        """
        if not files:
            return False
        safe_files = [f for f in files if f and not f.startswith("-")]
        if not safe_files:
            return False
        rc, _, err = _run(["git", "add", "--"] + safe_files, self.repo_path)
        if rc != 0:
            print(f"[GitAgent] stage_files error: {err}")
            return False
        return True

    # ── Commit ────────────────────────────────────────────────────────────

    def commit_changes(
        self, files: list, message: str, description: str = ""
    ) -> Optional[str]:
        """
        Stage files and create a commit.
        Auto-appends Co-Authored-By trailer.
        Returns commit hash or None on failure.
        """
        if not self.stage_files(files):
            return None

        full_message = message.strip()
        if description:
            full_message += f"\n\n{description.strip()}"
        full_message += "\n\nCo-Authored-By: Nexus Agent <nexus@local>"

        rc, out, err = _run(
            ["git", "commit", "-m", full_message],
            self.repo_path,
        )
        if rc != 0:
            print(f"[GitAgent] commit error: {err}")
            return None

        # Extract hash from "[(branch) abc1234] ..." output
        match = re.search(r"\b([0-9a-f]{7,40})\b", out)
        if match:
            return match.group(1)

        # Fallback: ask git directly
        rc2, hash_out, _ = _run(["git", "rev-parse", "HEAD"], self.repo_path)
        return hash_out if rc2 == 0 else None

    # ── Push ──────────────────────────────────────────────────────────────

    def push_branch(self, branch: str = None) -> bool:
        """
        Push branch to origin with -u (sets upstream).
        Returns True on success.
        """
        if branch is None:
            rc, branch, _ = _run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], self.repo_path
            )
            if rc != 0:
                return False

        rc, _, err = _run(
            ["git", "push", "-u", "origin", branch],
            self.repo_path,
            timeout=60,
        )
        if rc != 0:
            print(f"[GitAgent] push error: {err}")
            return False
        return True

    # ── Pull Request ──────────────────────────────────────────────────────

    def create_pr(
        self,
        base: str,
        title: str,
        body: str,
        draft: bool = False,
    ) -> str:
        """
        Create a GitHub PR using the `gh` CLI.
        Returns PR URL or empty string on failure.
        """
        if not self._has_github:
            print("[GitAgent] No GitHub remote — skipping PR creation")
            return ""

        cmd = [
            "gh", "pr", "create",
            "--base", base,
            "--title", title,
            "--body", body,
        ]
        if draft:
            cmd.append("--draft")

        rc, out, err = _run(cmd, self.repo_path, timeout=60)
        if rc != 0:
            print(f"[GitAgent] create_pr error: {err}")
            return ""
        # gh outputs the PR URL on the last line
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        return lines[-1] if lines else ""

    # ── PR Status ─────────────────────────────────────────────────────────

    def get_pr_status(self, pr_url: str) -> dict:
        """
        Fetch PR state, CI checks, and review status via `gh pr view`.
        Returns {state, ci_passing, review_status, checks: list}.
        """
        if not pr_url:
            return {"state": "unknown", "ci_passing": False, "review_status": "none", "checks": []}

        rc, out, err = _run(
            ["gh", "pr", "view", pr_url, "--json",
             "state,statusCheckRollup,reviews,mergeable"],
            self.repo_path,
            timeout=30,
        )
        if rc != 0:
            print(f"[GitAgent] get_pr_status error: {err}")
            return {"state": "unknown", "ci_passing": False, "review_status": "none", "checks": []}

        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return {"state": "unknown", "ci_passing": False, "review_status": "none", "checks": []}

        checks = data.get("statusCheckRollup", []) or []
        check_list = [
            {
                "name":       c.get("name", c.get("context", "")),
                "status":     c.get("status", ""),
                "conclusion": c.get("conclusion", c.get("state", "")),
            }
            for c in checks
        ]

        # CI passes when every check has conclusion SUCCESS/NEUTRAL or is skipped
        passing_conclusions = {"SUCCESS", "NEUTRAL", "SKIPPED", "success", "neutral", "skipped"}
        ci_passing = bool(check_list) and all(
            c["conclusion"].upper() in {s.upper() for s in passing_conclusions}
            for c in check_list
            if c["conclusion"]
        )

        reviews = data.get("reviews", []) or []
        approved = any(r.get("state") == "APPROVED" for r in reviews)
        changes_requested = any(r.get("state") == "CHANGES_REQUESTED" for r in reviews)
        review_status = (
            "approved" if approved
            else "changes_requested" if changes_requested
            else "pending"
        )

        return {
            "state":          data.get("state", "unknown"),
            "ci_passing":     ci_passing,
            "review_status":  review_status,
            "checks":         check_list,
            "mergeable":      data.get("mergeable", "UNKNOWN"),
        }

    # ── CI Watcher ────────────────────────────────────────────────────────

    def watch_ci(self, pr_url: str, timeout: int = 300) -> dict:
        """
        Poll CI status every 30 seconds until timeout.
        Returns {passed: bool, failed_jobs: list, duration: int}.
        """
        interval = 30
        start    = time.time()
        failed_jobs: list = []

        while True:
            elapsed = int(time.time() - start)
            pr_status = self.get_pr_status(pr_url)
            checks    = pr_status.get("checks", [])

            pending = [
                c for c in checks
                if c.get("status", "").upper() not in ("COMPLETED", "SUCCESS", "FAILURE",
                                                        "CANCELLED", "TIMED_OUT")
            ]
            failed_jobs = [
                c for c in checks
                if c.get("conclusion", "").upper() in ("FAILURE", "CANCELLED", "TIMED_OUT")
            ]

            if not pending:
                passed = bool(checks) and not failed_jobs
                return {"passed": passed, "failed_jobs": failed_jobs, "duration": elapsed}

            if elapsed >= timeout:
                return {
                    "passed":      False,
                    "failed_jobs": failed_jobs + pending,
                    "duration":    elapsed,
                    "timed_out":   True,
                }

            print(
                f"[GitAgent] CI: {len(pending)} check(s) pending "
                f"({elapsed}s / {timeout}s) — retrying in {interval}s"
            )
            time.sleep(interval)

    # ── Failing Test Parser ───────────────────────────────────────────────

    def get_failing_tests(self, pr_url: str) -> list:
        """
        Pull CI failure logs via `gh run view --log-failed` and parse test names.
        Returns list of {test_name, error_message, file, line}.
        """
        if not pr_url:
            return []

        # Find run ID associated with this PR
        rc, runs_out, _ = _run(
            ["gh", "pr", "checks", pr_url, "--json", "name,link,state"],
            self.repo_path, timeout=30,
        )
        failing: list = []
        if rc != 0:
            return failing

        try:
            checks = json.loads(runs_out)
        except json.JSONDecodeError:
            return failing

        for check in checks:
            if check.get("state", "").upper() not in ("FAILURE", "FAIL"):
                continue
            link = check.get("link", "")
            # Extract run ID from URL: .../runs/{run_id}/...
            m = re.search(r"/runs/(\d+)", link)
            if not m:
                continue
            run_id = m.group(1)
            rc2, log_out, _ = _run(
                ["gh", "run", "view", run_id, "--log-failed"],
                self.repo_path, timeout=60,
            )
            if rc2 != 0:
                continue

            for log_line in log_out.splitlines():
                # Jest/pytest style: "FAIL src/foo.test.js > test name"
                # or "FAILED tests/test_foo.py::test_bar"
                test_match = re.search(
                    r"(FAIL(?:ED)?)\s+([\w/.\-]+(?:\.test\.[jt]sx?|\.spec\.[jt]sx?|\.py))"
                    r"(?:\s+>?\s*(.+))?",
                    log_line,
                )
                if test_match:
                    file_    = test_match.group(2)
                    tname    = (test_match.group(3) or "").strip()
                    failing.append({
                        "test_name":     tname or file_,
                        "error_message": log_line.strip(),
                        "file":          file_,
                        "line":          "",
                    })
                    continue

                # Error lines: "Error: ..." or "AssertionError: ..."
                err_match = re.search(r"(Error|Exception|assert).*?:\s+(.+)", log_line)
                if err_match and failing:
                    # Enrich last entry
                    failing[-1]["error_message"] = log_line.strip()

        return failing

    # ── Auto-commit After Task ────────────────────────────────────────────

    def auto_commit_after_task(self, task: dict, result: dict) -> Optional[str]:
        """
        Called after a successful task (quality >= 70).
        1. Creates branch feature/{category}-{task_id}
        2. Stages any files written by the task
        3. Commits with the task title as message
        Returns commit hash or None if nothing to commit.
        """
        quality = result.get("quality", 0)
        if quality < 70:
            return None

        task_id  = task.get("id", "unknown")
        category = re.sub(r"[^a-z0-9_-]", "", task.get("category", "task").lower())
        title    = task.get("title", f"task-{task_id}")

        branch_name = f"feature/{category}-{task_id}"

        # Determine which files were written by this task
        files_written = result.get("files_written", [])
        if not files_written:
            # Check git status for modified/new files
            st = self.status()
            files_written = list(set(st["modified"] + st["untracked"] + st["staged"]))

        if not files_written:
            return None  # Nothing to commit

        try:
            # Create branch (safe: won't delete existing work)
            try:
                self.create_branch(branch_name)
            except RuntimeError:
                # Already on a feature branch or branch exists — commit there
                pass

            commit_hash = self.commit_changes(
                files=files_written,
                message=f"feat({category}): {title}",
                description=f"Task #{task_id} — auto-committed after quality={quality}/100",
            )
            if commit_hash:
                print(
                    f"[GitAgent] auto_commit task={task_id} "
                    f"quality={quality} branch={branch_name} hash={commit_hash}"
                )
            return commit_hash

        except Exception as exc:
            print(f"[GitAgent] auto_commit_after_task error: {exc}")
            return None

    # ── Entry Point ───────────────────────────────────────────────────────

    def run_action(self, task: dict) -> dict:
        """
        Route task by action key:
          commit   → commit_changes
          pr       → create_pr
          status   → status
          watch_ci → watch_ci
        """
        start  = time.time()
        action = task.get("action", "status")

        try:
            if action == "status":
                out = self.status()
                return {
                    "status":    "done",
                    "output":    json.dumps(out),
                    "quality":   100,
                    "elapsed_s": round(time.time() - start, 2),
                }

            elif action == "commit":
                files   = task.get("files", [])
                message = task.get("message", "chore: agent commit")
                desc    = task.get("description", "")
                h = self.commit_changes(files, message, desc)
                if h:
                    return {
                        "status":    "done",
                        "output":    h,
                        "quality":   90,
                        "elapsed_s": round(time.time() - start, 2),
                    }
                return {
                    "status":    "failed",
                    "output":    "commit returned None — nothing staged or error",
                    "quality":   0,
                    "elapsed_s": round(time.time() - start, 2),
                }

            elif action == "pr":
                base  = task.get("base", "main")
                title = task.get("title", "Agent PR")
                body  = task.get("body", "")
                draft = task.get("draft", False)
                url = self.create_pr(base, title, body, draft)
                if url:
                    return {
                        "status":    "done",
                        "output":    url,
                        "quality":   90,
                        "elapsed_s": round(time.time() - start, 2),
                    }
                return {
                    "status":    "failed",
                    "output":    "PR creation failed — check gh CLI auth",
                    "quality":   0,
                    "elapsed_s": round(time.time() - start, 2),
                }

            elif action == "watch_ci":
                pr_url  = task.get("pr_url", "")
                timeout = int(task.get("timeout", 300))
                result  = self.watch_ci(pr_url, timeout)
                quality = 100 if result.get("passed") else 0
                return {
                    "status":    "done" if result.get("passed") else "failed",
                    "output":    json.dumps(result),
                    "quality":   quality,
                    "elapsed_s": round(time.time() - start, 2),
                }

            else:
                return {
                    "status":    "failed",
                    "output":    f"Unknown action: {action}. Use: commit | pr | status | watch_ci",
                    "quality":   0,
                    "elapsed_s": round(time.time() - start, 2),
                }

        except Exception as exc:
            return {
                "status":    "failed",
                "output":    str(exc),
                "quality":   0,
                "elapsed_s": round(time.time() - start, 2),
            }


# ── Module-level run() — agent contract ──────────────────────────────────────

def run(task: dict) -> dict:
    """
    Standard agent entry point.
    task["repo_path"] is optional; defaults to cwd.
    task["action"] selects the operation.
    """
    repo_path = task.get("repo_path") or BASE_DIR
    try:
        agent = GitAgent(repo_path=repo_path)
    except ValueError as exc:
        return {
            "status":    "failed",
            "output":    str(exc),
            "quality":   0,
            "elapsed_s": 0.0,
            "agent":     "git_agent",
        }
    result = agent.run_action(task)
    result["agent"] = "git_agent"
    return result
