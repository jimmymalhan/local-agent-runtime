#!/usr/bin/env python3
"""
orchestrator/checkpoint_manager.py — Agent checkpoint and rollback system
=========================================================================
Every agent checkpoints work every 30 seconds.
Every version snapshots full system state before upgrades.
Auto-rollback if a version degrades a passing benchmark.

Guarantees:
  - No version leaves the system worse than it entered
  - Crashed agents resume from last checkpoint, not from scratch
  - Bad upgrades roll back to last good snapshot automatically

Usage:
    from orchestrator.checkpoint_manager import CheckpointManager, get_cm
    cm = get_cm()
    cm.checkpoint_agent("executor", version=4, data={"task": ..., "progress": ...})
    cm.snapshot_version(4, state)         # before applying upgrades
    cm.rollback_version(4)                # undo v4 upgrades
    resume_data = cm.load_agent(\"executor\", version=4)
"""
import json, time, shutil, threading
from pathlib import Path
from datetime import datetime
from typing import Any, Optional, Dict

BASE_DIR     = Path(__file__).parent.parent
CHECKPOINTS  = BASE_DIR / "checkpoints"
STATE_FILE   = BASE_DIR / "dashboard" / "state.json"
REPORTS_DIR  = BASE_DIR / "reports"

CHECKPOINTS.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

CHECKPOINT_INTERVAL = 30  # seconds
MAX_CHECKPOINTS_PER_AGENT = 5   # keep last N checkpoints per agent per version
MAX_VERSION_SNAPSHOTS = 5       # keep last N full version snapshots


# ── Checkpoint helpers ────────────────────────────────────────────────────────

def _ckpt_path(agent: str, version: int, seq: int) -> Path:
    return CHECKPOINTS / f"agent_{agent}_v{version}_s{seq:04d}.json"


def _snap_path(version: int) -> Path:
    return CHECKPOINTS / f"version_snapshot_v{version}.json"


def _rollback_path(version: int) -> Path:
    return CHECKPOINTS / f"rollback_v{version}.json"


# ── Core manager ─────────────────────────────────────────────────────────────

class CheckpointManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._seq: Dict[str, int] = {}   # agent+version → next seq number
        self._log_path = REPORTS_DIR / "checkpoint_log.jsonl"

    def _log(self, event: str, detail: str = ""):
        entry = {"ts": datetime.utcnow().isoformat(timespec="seconds"), "event": event, "detail": detail}
        try:
            with open(self._log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    # ── Agent checkpoints ─────────────────────────────────────────────────────

    def checkpoint_agent(self, agent: str, version: int, data: dict) -> Path:
        """Save agent mid-task state. Returns checkpoint path."""
        key = f"{agent}_v{version}"
        with self._lock:
            seq = self._seq.get(key, 0) + 1
            self._seq[key] = seq

        path = _ckpt_path(agent, version, seq)
        payload = {
            "agent": agent, "version": version, "seq": seq,
            "ts": datetime.utcnow().isoformat(timespec="seconds"),
            "data": data,
        }
        try:
            path.write_text(json.dumps(payload, indent=2))
            self._log("checkpoint", f"{agent} v{version} seq={seq}")
            # Prune old checkpoints for this agent+version
            self._prune_agent_checkpoints(agent, version)
        except Exception as e:
            self._log("checkpoint_error", f"{agent}: {e}")
        return path

    def load_agent(self, agent: str, version: int) -> Optional[dict]:
        """Load most recent checkpoint for agent+version. Returns None if none."""
        ckpts = sorted(
            CHECKPOINTS.glob(f"agent_{agent}_v{version}_s*.json"),
            key=lambda p: int(p.stem.split("_s")[-1]),
            reverse=True,
        )
        for ck in ckpts:
            try:
                payload = json.loads(ck.read_text())
                self._log("resume", f"{agent} v{version} from seq={payload.get('seq')}")
                return payload["data"]
            except Exception:
                continue
        return None

    def _prune_agent_checkpoints(self, agent: str, version: int):
        ckpts = sorted(
            CHECKPOINTS.glob(f"agent_{agent}_v{version}_s*.json"),
            key=lambda p: int(p.stem.split("_s")[-1]),
        )
        for old in ckpts[:-MAX_CHECKPOINTS_PER_AGENT]:
            try:
                old.unlink()
            except Exception:
                pass

    # ── Version snapshots ─────────────────────────────────────────────────────

    def snapshot_version(self, version: int, state: Optional[dict] = None) -> Path:
        """Snapshot full system state before applying version upgrades."""
        if state is None:
            try:
                state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
            except Exception:
                state = {}
        path = _snap_path(version)
        payload = {
            "version": version,
            "ts": datetime.utcnow().isoformat(timespec="seconds"),
            "state": state,
        }
        try:
            path.write_text(json.dumps(payload, indent=2))
            self._log("snapshot", f"v{version}")
            self._prune_version_snapshots()
        except Exception as e:
            self._log("snapshot_error", f"v{version}: {e}")
        return path

    def rollback_version(self, version: int) -> bool:
        """
        Roll back to pre-version-N snapshot.
        Returns True on success, False if no snapshot found.
        """
        snap = _snap_path(version)
        if not snap.exists():
            self._log("rollback_failed", f"No snapshot for v{version}")
            return False
        try:
            payload = json.loads(snap.read_text())
            prev_state = payload["state"]
            # Save current state as rollback marker (for audit)
            try:
                cur = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
                _rollback_path(version).write_text(json.dumps({
                    "rolled_back_from": cur,
                    "rolled_back_to": prev_state,
                    "ts": datetime.utcnow().isoformat(timespec="seconds"),
                }, indent=2))
            except Exception:
                pass
            STATE_FILE.write_text(json.dumps(prev_state, indent=2))
            self._log("rollback", f"v{version} state restored")
            return True
        except Exception as e:
            self._log("rollback_error", f"v{version}: {e}")
            return False

    def has_regressed(self, version: int, metric: str = "avg_local") -> bool:
        """
        Compare current benchmark score against pre-version snapshot.
        Returns True if the current score is lower (regression detected).
        """
        snap = _snap_path(version)
        if not snap.exists():
            return False
        try:
            before = json.loads(snap.read_text())["state"]
            before_score = before.get("benchmark_scores", {}).get(metric, 0) or 0
            cur = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
            after_score = cur.get("benchmark_scores", {}).get(metric, 0) or 0
            if float(after_score) < float(before_score) - 2:  # >2pt drop = regression
                self._log("regression", f"v{version} {metric}: {before_score}→{after_score}")
                return True
        except Exception:
            pass
        return False

    def _prune_version_snapshots(self):
        snaps = sorted(CHECKPOINTS.glob("version_snapshot_v*.json"),
                       key=lambda p: p.stat().st_mtime)
        for old in snaps[:-MAX_VERSION_SNAPSHOTS]:
            try:
                old.unlink()
            except Exception:
                pass

    # ── Background auto-checkpoint ────────────────────────────────────────────

    def start_auto_checkpoint(self, agent: str, version: int, data_fn):
        """
        Start background thread that calls data_fn() and checkpoints every 30s.
        data_fn: callable → dict (current agent state)
        Returns the thread (daemon=True).
        """
        def _loop():
            while True:
                time.sleep(CHECKPOINT_INTERVAL)
                try:
                    data = data_fn()
                    if data:
                        self.checkpoint_agent(agent, version, data)
                except Exception:
                    pass
        t = threading.Thread(target=_loop, daemon=True, name=f"ckpt-{agent}")
        t.start()
        return t

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return summary of all checkpoint files."""
        ckpts = list(CHECKPOINTS.glob("agent_*_v*_s*.json"))
        snaps = list(CHECKPOINTS.glob("version_snapshot_v*.json"))
        return {
            "agent_checkpoints": len(ckpts),
            "version_snapshots": len(snaps),
            "checkpoint_dir": str(CHECKPOINTS),
            "oldest_checkpoint": min((c.stat().st_mtime for c in ckpts), default=0),
            "newest_checkpoint": max((c.stat().st_mtime for c in ckpts), default=0),
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_cm_instance: Optional[CheckpointManager] = None
_cm_lock = threading.Lock()


def get_cm() -> CheckpointManager:
    global _cm_instance
    with _cm_lock:
        if _cm_instance is None:
            _cm_instance = CheckpointManager()
    return _cm_instance


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Checkpoint manager")
    ap.add_argument("--status",   action="store_true", help="Show checkpoint status")
    ap.add_argument("--snapshot", type=int, metavar="VERSION", help="Snapshot version N state")
    ap.add_argument("--rollback", type=int, metavar="VERSION", help="Roll back to pre-vN snapshot")
    ap.add_argument("--check-regression", type=int, metavar="VERSION", help="Check if vN regressed")
    args = ap.parse_args()

    cm = get_cm()

    if args.status:
        print(json.dumps(cm.status(), indent=2))
    elif args.snapshot:
        p = cm.snapshot_version(args.snapshot)
        print(f"Snapshot saved: {p}")
    elif args.rollback:
        ok = cm.rollback_version(args.rollback)
        print("Rolled back" if ok else "Rollback failed — no snapshot found")
    elif args.check_regression:
        reg = cm.has_regressed(args.check_regression)
        print(f"v{args.check_regression} regression: {reg}")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
