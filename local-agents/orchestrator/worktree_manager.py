"""
worktree_manager.py — Git worktree isolation for parallel agent execution.

Each agent gets its own isolated working tree. Changes are sandboxed.
If agent fails, just remove its worktree. Others unaffected.

Usage:
    mgr = WorktreeManager()
    path = mgr.allocate("agent-1", base_branch="main")
    # agent works in path
    branch = mgr.merge_or_discard("agent-1", quality=85)
    # if quality >= threshold: merge back, else discard
"""
import subprocess, json, shutil
from pathlib import Path
from datetime import datetime

WORKTREE_BASE = Path(".nexus/worktrees")
REGISTRY = Path(".nexus/worktrees/registry.json")

class WorktreeManager:
    def __init__(self, repo_path: str = "."):
        self.repo = Path(repo_path).resolve()
        WORKTREE_BASE.mkdir(parents=True, exist_ok=True)

    def _run(self, cmd: list, cwd=None) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd or self.repo)

    def _load_registry(self) -> dict:
        if REGISTRY.exists():
            try: return json.loads(REGISTRY.read_text())
            except: pass
        return {}

    def _save_registry(self, reg: dict):
        REGISTRY.write_text(json.dumps(reg, indent=2))

    def allocate(self, agent_id: str, base_branch: str = "main", task_id: str = "") -> str:
        """Create isolated worktree for agent. Returns path to worktree."""
        reg = self._load_registry()
        if agent_id in reg:
            return reg[agent_id]["path"]  # already allocated

        branch_name = f"agent/{agent_id[:8]}-{datetime.utcnow().strftime('%H%M%S')}"
        worktree_path = str(WORKTREE_BASE / agent_id)

        # Create branch from base
        r = self._run(["git", "worktree", "add", "-b", branch_name, worktree_path, base_branch])
        if r.returncode != 0:
            raise RuntimeError(f"Failed to create worktree: {r.stderr}")

        reg[agent_id] = {
            "path": worktree_path,
            "branch": branch_name,
            "base_branch": base_branch,
            "task_id": task_id,
            "created": datetime.utcnow().isoformat(),
            "status": "active"
        }
        self._save_registry(reg)
        return worktree_path

    def release(self, agent_id: str) -> bool:
        """Remove worktree without merging (discard changes)."""
        reg = self._load_registry()
        if agent_id not in reg: return False

        entry = reg[agent_id]
        self._run(["git", "worktree", "remove", "--force", entry["path"]])
        self._run(["git", "branch", "-D", entry["branch"]])
        del reg[agent_id]
        self._save_registry(reg)
        return True

    def commit_and_merge(self, agent_id: str, commit_message: str) -> dict:
        """Commit changes in worktree and merge to base branch."""
        reg = self._load_registry()
        if agent_id not in reg:
            raise ValueError(f"No worktree for {agent_id}")

        entry = reg[agent_id]
        wt_path = entry["path"]

        # Stage and commit in worktree
        self._run(["git", "add", "-A"], cwd=wt_path)
        r = self._run(["git", "commit", "-m", commit_message], cwd=wt_path)
        if r.returncode != 0 and "nothing to commit" not in r.stdout:
            return {"ok": False, "error": r.stderr}

        # Merge back to base
        self._run(["git", "checkout", entry["base_branch"]])
        r = self._run(["git", "merge", "--no-ff", entry["branch"], "-m", f"Merge agent/{agent_id}: {commit_message}"])
        if r.returncode != 0:
            return {"ok": False, "error": f"Merge conflict: {r.stderr}"}

        # Cleanup
        self.release(agent_id)
        return {"ok": True, "branch": entry["branch"]}

    def merge_or_discard(self, agent_id: str, quality: int, commit_message: str = "", threshold: int = 60) -> dict:
        """If quality >= threshold: merge. Else: discard."""
        if quality >= threshold:
            msg = commit_message or f"feat: agent {agent_id} task (quality={quality})"
            return self.commit_and_merge(agent_id, msg)
        else:
            self.release(agent_id)
            return {"ok": False, "discarded": True, "reason": f"quality {quality} < threshold {threshold}"}

    def list_active(self) -> list:
        reg = self._load_registry()
        return [
            {"agent_id": k, "branch": v["branch"], "created": v["created"],
             "task_id": v["task_id"], "path": v["path"]}
            for k, v in reg.items()
        ]

    def cleanup_stale(self, max_age_hours: int = 4):
        """Remove worktrees older than max_age_hours"""
        reg = self._load_registry()
        now = datetime.utcnow()
        for agent_id, entry in list(reg.items()):
            created = datetime.fromisoformat(entry["created"])
            age_hours = (now - created).total_seconds() / 3600
            if age_hours > max_age_hours:
                self.release(agent_id)
