#!/usr/bin/env python3
"""
orchestrator/snapshot_recovery.py — Periodic Snapshot & Fast Crash Recovery
===========================================================================
Takes periodic full-system snapshots and recovers from crashes in <1 second
by restoring the latest valid snapshot then replaying the WAL tail.

Architecture:
  1. SnapshotStore: atomic, CRC-verified, compressed snapshots on disk
  2. SnapshotScheduler: background thread taking snapshots at configurable intervals
  3. RecoveryManager: crash detection (stale heartbeat / lock file) + fast restore
  4. SystemState: collects all runtime state into a single serializable dict

Recovery flow:
  - Load latest valid snapshot (CRC check + decompress)
  - Replay WAL entries written after snapshot's last_lsn
  - Verify integrity, update heartbeat, resume

Usage:
    from orchestrator.snapshot_recovery import RecoveryManager, SnapshotScheduler
    rm = RecoveryManager("/path/to/data")
    state = rm.recover()  # fast restore on startup
    sched = SnapshotScheduler(rm, interval=60)
    sched.start()
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import signal
import struct
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SNAPSHOT_MAGIC = b"SNAP"          # 4-byte file header
SNAPSHOT_VERSION = 1              # format version
DEFAULT_INTERVAL = 60             # seconds between periodic snapshots
MAX_SNAPSHOTS = 10                # keep last N snapshots
HEARTBEAT_STALE_SEC = 120         # if heartbeat older than this, assume crash
LOCK_STALE_SEC = 300              # lock file older than this = dead process


# ---------------------------------------------------------------------------
# SystemState — aggregate all runtime state
# ---------------------------------------------------------------------------

@dataclass
class SystemState:
    """Serializable snapshot of the entire runtime."""
    timestamp: float
    agents: dict[str, Any]             # agent_name -> state dict
    tasks: dict[str, Any]              # task_id -> task dict
    orchestrator: dict[str, Any]       # orchestrator metadata
    metrics: dict[str, Any]            # counters, success rates, etc.
    wal_lsn: int                       # WAL LSN at snapshot time
    version: int                       # system version number
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> SystemState:
        return SystemState(
            timestamp=d["timestamp"],
            agents=d.get("agents", {}),
            tasks=d.get("tasks", {}),
            orchestrator=d.get("orchestrator", {}),
            metrics=d.get("metrics", {}),
            wal_lsn=d.get("wal_lsn", -1),
            version=d.get("version", 0),
            extra=d.get("extra", {}),
        )

    @staticmethod
    def empty() -> SystemState:
        return SystemState(
            timestamp=time.time(),
            agents={},
            tasks={},
            orchestrator={},
            metrics={},
            wal_lsn=-1,
            version=0,
        )


# ---------------------------------------------------------------------------
# SnapshotStore — atomic, compressed, CRC-verified snapshots
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SnapshotMeta:
    """Metadata header written with each snapshot."""
    snapshot_id: int
    timestamp: float
    wal_lsn: int
    checksum: str          # SHA-256 of the compressed payload
    size_bytes: int        # uncompressed JSON size
    compressed_bytes: int  # gzipped size


class SnapshotStore:
    """Manages snapshot files on disk with integrity verification."""

    def __init__(self, data_dir: Path) -> None:
        self.snapshot_dir = data_dir / "snapshots" / "system"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self._next_id = self._find_next_id()

    def _snap_path(self, snapshot_id: int) -> Path:
        return self.snapshot_dir / f"system_{snapshot_id:08d}.snap.gz"

    def _meta_path(self, snapshot_id: int) -> Path:
        return self.snapshot_dir / f"system_{snapshot_id:08d}.meta.json"

    def _find_next_id(self) -> int:
        metas = sorted(self.snapshot_dir.glob("system_*.meta.json"))
        if not metas:
            return 0
        name = metas[-1].stem.replace(".meta", "")
        return int(name.split("_")[1]) + 1

    # --- Write ---

    def save(self, state: SystemState) -> SnapshotMeta:
        """
        Atomically save a snapshot:
        1. Serialize to JSON
        2. Compress with gzip
        3. Compute SHA-256 of compressed data
        4. Write to temp file, fsync, rename (atomic on POSIX)
        5. Write metadata
        6. Prune old snapshots
        """
        snapshot_id = self._next_id
        self._next_id += 1

        # Serialize + compress
        raw_json = json.dumps(state.to_dict(), separators=(",", ":"), sort_keys=True)
        raw_bytes = raw_json.encode("utf-8")
        compressed = gzip.compress(raw_bytes, compresslevel=6)
        checksum = hashlib.sha256(compressed).hexdigest()

        meta = SnapshotMeta(
            snapshot_id=snapshot_id,
            timestamp=state.timestamp,
            wal_lsn=state.wal_lsn,
            checksum=checksum,
            size_bytes=len(raw_bytes),
            compressed_bytes=len(compressed),
        )

        # Atomic write: temp file -> fsync -> rename
        snap_path = self._snap_path(snapshot_id)
        tmp_snap = snap_path.with_suffix(".tmp")
        with open(tmp_snap, "wb") as f:
            f.write(SNAPSHOT_MAGIC)
            f.write(struct.pack("<H", SNAPSHOT_VERSION))
            f.write(compressed)
            f.flush()
            os.fsync(f.fileno())
        os.rename(str(tmp_snap), str(snap_path))

        # Write metadata
        meta_path = self._meta_path(snapshot_id)
        tmp_meta = meta_path.with_suffix(".tmp")
        with open(tmp_meta, "w") as f:
            json.dump(asdict(meta), f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.rename(str(tmp_meta), str(meta_path))

        self._prune()
        return meta

    # --- Read ---

    def load_latest(self) -> tuple[SystemState, SnapshotMeta] | None:
        """Load the most recent valid snapshot. Skips corrupted ones."""
        metas = sorted(self.snapshot_dir.glob("system_*.meta.json"), reverse=True)
        for meta_path in metas:
            try:
                result = self._load_snapshot(meta_path)
                if result is not None:
                    return result
            except Exception:
                continue
        return None

    def _load_snapshot(self, meta_path: Path) -> tuple[SystemState, SnapshotMeta] | None:
        """Load and verify a single snapshot. Returns None if corrupted."""
        with open(meta_path, "r") as f:
            meta_dict = json.load(f)
        meta = SnapshotMeta(**meta_dict)

        snap_path = self._snap_path(meta.snapshot_id)
        if not snap_path.exists():
            return None

        with open(snap_path, "rb") as f:
            magic = f.read(4)
            if magic != SNAPSHOT_MAGIC:
                return None
            version = struct.unpack("<H", f.read(2))[0]
            if version != SNAPSHOT_VERSION:
                return None
            compressed = f.read()

        # Verify checksum
        actual_checksum = hashlib.sha256(compressed).hexdigest()
        if actual_checksum != meta.checksum:
            return None

        # Decompress and parse
        raw_bytes = gzip.decompress(compressed)
        if len(raw_bytes) != meta.size_bytes:
            return None

        state_dict = json.loads(raw_bytes.decode("utf-8"))
        state = SystemState.from_dict(state_dict)
        return state, meta

    def load_by_id(self, snapshot_id: int) -> tuple[SystemState, SnapshotMeta] | None:
        """Load a specific snapshot by ID."""
        meta_path = self._meta_path(snapshot_id)
        if not meta_path.exists():
            return None
        return self._load_snapshot(meta_path)

    def list_snapshots(self) -> list[SnapshotMeta]:
        """List all valid snapshot metadata, newest first."""
        result = []
        for meta_path in sorted(self.snapshot_dir.glob("system_*.meta.json"), reverse=True):
            try:
                with open(meta_path, "r") as f:
                    result.append(SnapshotMeta(**json.load(f)))
            except Exception:
                continue
        return result

    # --- Maintenance ---

    def _prune(self) -> None:
        """Remove old snapshots beyond MAX_SNAPSHOTS."""
        metas = sorted(self.snapshot_dir.glob("system_*.meta.json"))
        for old_meta in metas[:-MAX_SNAPSHOTS]:
            try:
                sid = int(old_meta.stem.replace(".meta", "").split("_")[1])
                self._snap_path(sid).unlink(missing_ok=True)
                old_meta.unlink(missing_ok=True)
            except Exception:
                pass

    def verify_all(self) -> tuple[int, int, list[int]]:
        """
        Verify integrity of all snapshots.
        Returns (total, valid_count, corrupted_ids).
        """
        metas = self.list_snapshots()
        corrupted = []
        for meta in metas:
            result = self.load_by_id(meta.snapshot_id)
            if result is None:
                corrupted.append(meta.snapshot_id)
        return len(metas), len(metas) - len(corrupted), corrupted


# ---------------------------------------------------------------------------
# Heartbeat — crash detection via stale heartbeat file
# ---------------------------------------------------------------------------

class Heartbeat:
    """Writes periodic heartbeat to detect crashes on next startup."""

    def __init__(self, data_dir: Path) -> None:
        self.hb_path = data_dir / "heartbeat.json"
        self.lock_path = data_dir / "process.lock"
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def is_stale(self) -> bool:
        """Check if last heartbeat is older than threshold (crash indicator)."""
        if not self.hb_path.exists():
            return False  # first run, not a crash
        try:
            data = json.loads(self.hb_path.read_text())
            last_beat = data.get("timestamp", 0)
            return (time.time() - last_beat) > HEARTBEAT_STALE_SEC
        except Exception:
            return True  # corrupted heartbeat = treat as crash

    def has_stale_lock(self) -> bool:
        """Check for stale lock file from a dead process."""
        if not self.lock_path.exists():
            return False
        try:
            age = time.time() - self.lock_path.stat().st_mtime
            return age > LOCK_STALE_SEC
        except Exception:
            return False

    def acquire_lock(self) -> bool:
        """Acquire process lock. Returns False if another process holds it."""
        if self.lock_path.exists() and not self.has_stale_lock():
            try:
                data = json.loads(self.lock_path.read_text())
                pid = data.get("pid", 0)
                # Check if process is still alive
                try:
                    os.kill(pid, 0)
                    return False  # process alive, can't acquire
                except OSError:
                    pass  # process dead, safe to take over
            except Exception:
                pass

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_data = {
            "pid": os.getpid(),
            "timestamp": time.time(),
            "hostname": os.uname().nodename,
        }
        self.lock_path.write_text(json.dumps(lock_data))
        return True

    def release_lock(self) -> None:
        """Release process lock."""
        try:
            self.lock_path.unlink(missing_ok=True)
        except Exception:
            pass

    def beat(self) -> None:
        """Write a single heartbeat."""
        self.hb_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "pid": os.getpid(),
            "timestamp": time.time(),
            "uptime": time.monotonic(),
        }
        tmp = self.hb_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.rename(str(tmp), str(self.hb_path))

    def start(self, interval: float = 10.0) -> None:
        """Start background heartbeat thread."""
        self._stop.clear()

        def _loop():
            while not self._stop.is_set():
                self.beat()
                self._stop.wait(interval)

        self._thread = threading.Thread(target=_loop, daemon=True, name="heartbeat")
        self._thread.start()

    def stop(self) -> None:
        """Stop heartbeat and release lock."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self.release_lock()


# ---------------------------------------------------------------------------
# WAL Replay Adapter — replays WAL entries after a snapshot
# ---------------------------------------------------------------------------

class WALReplayer:
    """
    Replays WAL entries that occurred after a snapshot's wal_lsn
    to bring SystemState up to date.
    """

    def __init__(self, wal_dir: Path) -> None:
        self.wal_dir = wal_dir

    def replay_after(self, state: SystemState, from_lsn: int) -> SystemState:
        """
        Read WAL entries with LSN > from_lsn and apply them to state.
        Returns updated state.
        """
        entries = self._read_wal_entries(from_lsn)
        if not entries:
            return state

        for entry in entries:
            state = self._apply_entry(state, entry)

        # Update WAL LSN to the last replayed entry
        if entries:
            state.wal_lsn = entries[-1].get("lsn", state.wal_lsn)
            state.timestamp = time.time()

        return state

    def _read_wal_entries(self, after_lsn: int) -> list[dict]:
        """Read all WAL entries with LSN > after_lsn from segment files."""
        entries = []
        if not self.wal_dir.exists():
            return entries

        segments = sorted(self.wal_dir.glob("segment_*.wal"))
        for seg_path in segments:
            try:
                with open(seg_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        record = json.loads(line)
                        if record.get("lsn", -1) > after_lsn:
                            entries.append(record)
            except Exception:
                continue

        entries.sort(key=lambda e: e.get("lsn", 0))
        return entries

    def _apply_entry(self, state: SystemState, entry: dict) -> SystemState:
        """Apply a single WAL entry to the system state."""
        event_type = entry.get("event_type", "")
        payload = entry.get("payload", {})

        if event_type.startswith("task."):
            task_id = payload.get("aggregate_id") or payload.get("task_id", "")
            if task_id:
                if event_type == "task.created":
                    state.tasks[task_id] = payload
                elif event_type == "task.completed":
                    if task_id in state.tasks:
                        state.tasks[task_id]["status"] = "completed"
                elif event_type == "task.failed":
                    if task_id in state.tasks:
                        state.tasks[task_id]["status"] = "failed"
                elif event_type == "task.assigned":
                    if task_id in state.tasks:
                        state.tasks[task_id]["assignee"] = payload.get("assignee")

        elif event_type.startswith("agent."):
            agent_name = payload.get("agent", payload.get("name", ""))
            if agent_name:
                if agent_name not in state.agents:
                    state.agents[agent_name] = {}
                if event_type == "agent.started":
                    state.agents[agent_name]["status"] = "running"
                elif event_type == "agent.stopped":
                    state.agents[agent_name]["status"] = "stopped"
                elif event_type == "agent.checkpoint":
                    state.agents[agent_name].update(payload.get("data", {}))

        elif event_type.startswith("metric."):
            metric_name = payload.get("name", event_type)
            state.metrics[metric_name] = payload.get("value", payload)

        return state


# ---------------------------------------------------------------------------
# RecoveryManager — orchestrates snapshot + WAL recovery
# ---------------------------------------------------------------------------

@dataclass
class RecoveryResult:
    """Result of a recovery operation."""
    recovered: bool
    from_snapshot: bool
    snapshot_id: Optional[int]
    wal_entries_replayed: int
    crash_detected: bool
    recovery_time_ms: float
    state: SystemState

    def to_dict(self) -> dict:
        d = {
            "recovered": self.recovered,
            "from_snapshot": self.from_snapshot,
            "snapshot_id": self.snapshot_id,
            "wal_entries_replayed": self.wal_entries_replayed,
            "crash_detected": self.crash_detected,
            "recovery_time_ms": round(self.recovery_time_ms, 2),
        }
        return d


class RecoveryManager:
    """
    Coordinates snapshot creation and crash recovery.

    On startup:
      1. Check heartbeat for crash detection
      2. Load latest valid snapshot
      3. Replay WAL tail (entries after snapshot)
      4. Resume with recovered state
    """

    def __init__(
        self,
        data_dir: str | Path,
        wal_dir: str | Path | None = None,
        state_collector: Optional[Callable[[], SystemState]] = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.store = SnapshotStore(self.data_dir)
        self.heartbeat = Heartbeat(self.data_dir)
        self.wal_replayer = WALReplayer(Path(wal_dir) if wal_dir else self.data_dir / "wal")
        self._state_collector = state_collector
        self._current_state: Optional[SystemState] = None

        # Recovery log
        self._log_path = self.data_dir / "recovery_log.jsonl"

    def _log(self, event: str, detail: dict | str = "") -> None:
        entry = {"ts": time.time(), "event": event, "detail": detail}
        try:
            with open(self._log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    # --- Recovery ---

    def recover(self) -> RecoveryResult:
        """
        Perform crash recovery. Fast path: snapshot + WAL replay.
        Returns RecoveryResult with the restored state.
        """
        start = time.monotonic()
        crash_detected = self.heartbeat.is_stale() or self.heartbeat.has_stale_lock()

        if crash_detected:
            self._log("crash_detected", {
                "stale_heartbeat": self.heartbeat.is_stale(),
                "stale_lock": self.heartbeat.has_stale_lock(),
            })

        # Try loading latest snapshot
        snapshot_result = self.store.load_latest()
        wal_replayed = 0

        if snapshot_result is not None:
            state, meta = snapshot_result
            self._log("snapshot_loaded", {
                "id": meta.snapshot_id,
                "wal_lsn": meta.wal_lsn,
                "age_sec": round(time.time() - meta.timestamp, 1),
            })

            # Replay WAL entries after snapshot
            before_tasks = len(state.tasks)
            state = self.wal_replayer.replay_after(state, meta.wal_lsn)
            wal_replayed = len(state.tasks) - before_tasks  # approximate

            self._current_state = state
            elapsed = (time.monotonic() - start) * 1000

            result = RecoveryResult(
                recovered=True,
                from_snapshot=True,
                snapshot_id=meta.snapshot_id,
                wal_entries_replayed=wal_replayed,
                crash_detected=crash_detected,
                recovery_time_ms=elapsed,
                state=state,
            )
        else:
            # No snapshot — cold start
            state = SystemState.empty()
            state = self.wal_replayer.replay_after(state, -1)
            self._current_state = state
            elapsed = (time.monotonic() - start) * 1000

            result = RecoveryResult(
                recovered=True,
                from_snapshot=False,
                snapshot_id=None,
                wal_entries_replayed=0,
                crash_detected=crash_detected,
                recovery_time_ms=elapsed,
                state=state,
            )

        self._log("recovery_complete", result.to_dict())

        # Start heartbeat for this session
        self.heartbeat.acquire_lock()
        self.heartbeat.beat()

        return result

    # --- Snapshot creation ---

    def take_snapshot(self, state: Optional[SystemState] = None) -> SnapshotMeta:
        """
        Take a snapshot of the current system state.
        If state not provided, uses the state_collector callback or current_state.
        """
        if state is None:
            if self._state_collector:
                state = self._state_collector()
            elif self._current_state:
                state = self._current_state
            else:
                state = SystemState.empty()

        state.timestamp = time.time()
        meta = self.store.save(state)
        self._log("snapshot_taken", {
            "id": meta.snapshot_id,
            "wal_lsn": meta.wal_lsn,
            "size": meta.size_bytes,
            "compressed": meta.compressed_bytes,
        })
        return meta

    # --- State access ---

    @property
    def current_state(self) -> Optional[SystemState]:
        return self._current_state

    @current_state.setter
    def current_state(self, state: SystemState) -> None:
        self._current_state = state

    # --- Shutdown ---

    def shutdown(self) -> None:
        """Clean shutdown: take final snapshot, stop heartbeat, release lock."""
        if self._current_state or self._state_collector:
            try:
                self.take_snapshot()
                self._log("shutdown_snapshot", "final snapshot saved")
            except Exception as e:
                self._log("shutdown_snapshot_error", str(e))
        self.heartbeat.stop()
        self._log("shutdown", "clean")


# ---------------------------------------------------------------------------
# SnapshotScheduler — periodic background snapshots
# ---------------------------------------------------------------------------

class SnapshotScheduler:
    """
    Background thread that takes periodic snapshots.
    Configurable interval, with jitter to avoid thundering herd.
    """

    def __init__(
        self,
        recovery_mgr: RecoveryManager,
        interval: float = DEFAULT_INTERVAL,
    ) -> None:
        self.recovery_mgr = recovery_mgr
        self.interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._snapshot_count = 0

    def start(self) -> None:
        """Start the periodic snapshot thread."""
        self._stop.clear()

        def _loop():
            while not self._stop.is_set():
                self._stop.wait(self.interval)
                if self._stop.is_set():
                    break
                try:
                    self.recovery_mgr.take_snapshot()
                    self._snapshot_count += 1
                except Exception:
                    pass

        self._thread = threading.Thread(target=_loop, daemon=True, name="snapshot-scheduler")
        self._thread.start()

    def stop(self) -> None:
        """Stop the scheduler."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    @property
    def snapshot_count(self) -> int:
        return self._snapshot_count


# ---------------------------------------------------------------------------
# Main — verify correctness with assertions
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import shutil

    test_dir = Path(tempfile.mkdtemp(prefix="snap_recovery_test_"))

    try:
        # === Test 1: SnapshotStore — save and load ===
        print("Test 1: SnapshotStore save/load...")
        store = SnapshotStore(test_dir / "t1")
        state = SystemState(
            timestamp=time.time(),
            agents={"executor": {"status": "running", "tasks_done": 5}},
            tasks={"t-1": {"title": "Build API", "status": "in_progress"}},
            orchestrator={"version": 5, "mode": "autonomous"},
            metrics={"success_rate": 0.85, "total_tasks": 100},
            wal_lsn=42,
            version=5,
        )
        meta = store.save(state)
        assert meta.snapshot_id == 0, f"Expected id=0, got {meta.snapshot_id}"
        assert meta.wal_lsn == 42
        assert meta.size_bytes > 0
        assert meta.compressed_bytes > 0
        assert meta.compressed_bytes <= meta.size_bytes  # compression works

        result = store.load_latest()
        assert result is not None
        loaded_state, loaded_meta = result
        assert loaded_state.wal_lsn == 42
        assert loaded_state.agents["executor"]["tasks_done"] == 5
        assert loaded_state.tasks["t-1"]["title"] == "Build API"
        assert loaded_state.version == 5
        assert loaded_meta.checksum == meta.checksum
        print("  PASS")

        # === Test 2: CRC integrity — tampered snapshot detected ===
        print("Test 2: Integrity check detects corruption...")
        store2 = SnapshotStore(test_dir / "t2")
        store2.save(state)

        # Tamper with the snapshot file
        snap_file = list((test_dir / "t2" / "snapshots" / "system").glob("*.snap.gz"))[0]
        data = snap_file.read_bytes()
        tampered = data[:-10] + b"\x00" * 10  # corrupt last 10 bytes
        snap_file.write_bytes(tampered)

        result = store2.load_latest()
        assert result is None, "Corrupted snapshot should not load"
        print("  PASS")

        # === Test 3: Multiple snapshots + pruning ===
        print("Test 3: Multiple snapshots and pruning...")
        store3 = SnapshotStore(test_dir / "t3")
        for i in range(15):
            s = SystemState(
                timestamp=time.time(),
                agents={}, tasks={}, orchestrator={},
                metrics={"i": i}, wal_lsn=i, version=i,
            )
            store3.save(s)

        snapshots = store3.list_snapshots()
        assert len(snapshots) <= MAX_SNAPSHOTS, f"Expected <= {MAX_SNAPSHOTS}, got {len(snapshots)}"

        # Latest should be the last one saved
        result = store3.load_latest()
        assert result is not None
        assert result[0].wal_lsn == 14
        print("  PASS")

        # === Test 4: Snapshot verification ===
        print("Test 4: Verify all snapshots...")
        total, valid, corrupted = store3.verify_all()
        assert valid == total, f"Expected all valid, got {valid}/{total}, corrupted: {corrupted}"
        assert corrupted == [], f"Unexpected corrupted: {corrupted}"
        print("  PASS")

        # === Test 5: Load by ID ===
        print("Test 5: Load specific snapshot by ID...")
        latest_meta = store3.list_snapshots()[0]
        result = store3.load_by_id(latest_meta.snapshot_id)
        assert result is not None
        assert result[1].snapshot_id == latest_meta.snapshot_id
        # Non-existent ID
        assert store3.load_by_id(9999) is None
        print("  PASS")

        # === Test 6: Heartbeat — crash detection ===
        print("Test 6: Heartbeat crash detection...")
        hb = Heartbeat(test_dir / "t6")
        assert hb.is_stale() is False, "No heartbeat file = first run, not stale"

        hb.beat()
        assert hb.is_stale() is False, "Fresh heartbeat should not be stale"

        # Simulate stale heartbeat
        stale_data = {"pid": os.getpid(), "timestamp": time.time() - HEARTBEAT_STALE_SEC - 10}
        hb.hb_path.write_text(json.dumps(stale_data))
        assert hb.is_stale() is True, "Old heartbeat should be stale"
        print("  PASS")

        # === Test 7: Process lock ===
        print("Test 7: Process lock acquire/release...")
        hb7 = Heartbeat(test_dir / "t7")
        assert hb7.acquire_lock() is True, "Should acquire fresh lock"

        # Same process can re-acquire (pid check passes since process is alive,
        # but our process IS the holder)
        hb7.release_lock()
        assert not hb7.lock_path.exists(), "Lock should be released"

        # Stale lock from dead process
        hb7.lock_path.write_text(json.dumps({"pid": 99999999, "timestamp": time.time() - 1}))
        assert hb7.acquire_lock() is True, "Should acquire lock from dead process"
        hb7.release_lock()
        print("  PASS")

        # === Test 8: WALReplayer ===
        print("Test 8: WAL replay after snapshot...")
        wal_dir = test_dir / "t8" / "wal"
        wal_dir.mkdir(parents=True, exist_ok=True)

        # Write some WAL entries
        entries = [
            {"lsn": 0, "timestamp": time.time(), "event_type": "task.created",
             "payload": {"aggregate_id": "t-1", "title": "First task"}, "crc": 0, "segment_id": 0},
            {"lsn": 1, "timestamp": time.time(), "event_type": "task.created",
             "payload": {"aggregate_id": "t-2", "title": "Second task"}, "crc": 0, "segment_id": 0},
            {"lsn": 2, "timestamp": time.time(), "event_type": "task.completed",
             "payload": {"aggregate_id": "t-1"}, "crc": 0, "segment_id": 0},
            {"lsn": 3, "timestamp": time.time(), "event_type": "agent.started",
             "payload": {"agent": "executor"}, "crc": 0, "segment_id": 0},
            {"lsn": 4, "timestamp": time.time(), "event_type": "metric.recorded",
             "payload": {"name": "throughput", "value": 42}, "crc": 0, "segment_id": 0},
        ]
        seg_file = wal_dir / "segment_000000.wal"
        with open(seg_file, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

        replayer = WALReplayer(wal_dir)
        base_state = SystemState.empty()

        # Replay all entries (from LSN -1)
        recovered = replayer.replay_after(base_state, -1)
        assert "t-1" in recovered.tasks, "t-1 should be in tasks"
        assert "t-2" in recovered.tasks, "t-2 should be in tasks"
        assert recovered.tasks["t-1"].get("status") == "completed"
        assert recovered.agents.get("executor", {}).get("status") == "running"
        assert recovered.metrics.get("throughput") == 42

        # Replay only entries after LSN 2
        base_state2 = SystemState.empty()
        base_state2.tasks["t-1"] = {"title": "First task", "status": "completed"}
        base_state2.tasks["t-2"] = {"title": "Second task"}
        partial = replayer.replay_after(base_state2, 2)
        assert partial.agents.get("executor", {}).get("status") == "running"
        print("  PASS")

        # === Test 9: RecoveryManager — full recovery flow ===
        print("Test 9: Full recovery flow...")
        rm_dir = test_dir / "t9"
        rm = RecoveryManager(rm_dir, wal_dir=wal_dir)

        # First recovery — no snapshot, should do cold start + WAL replay
        result = rm.recover()
        assert result.recovered is True
        assert result.from_snapshot is False
        assert result.crash_detected is False
        assert result.recovery_time_ms >= 0

        # Take a snapshot
        rm.current_state = SystemState(
            timestamp=time.time(),
            agents={"executor": {"status": "running"}},
            tasks={"t-100": {"title": "Checkpoint task"}},
            orchestrator={"mode": "auto"},
            metrics={"rate": 0.9},
            wal_lsn=10,
            version=5,
        )
        meta = rm.take_snapshot()
        assert meta.snapshot_id == 0

        # Simulate crash: write stale heartbeat
        stale_hb = {"pid": os.getpid(), "timestamp": time.time() - HEARTBEAT_STALE_SEC - 10}
        rm.heartbeat.hb_path.write_text(json.dumps(stale_hb))

        # New recovery manager (simulating restart after crash)
        rm2 = RecoveryManager(rm_dir, wal_dir=wal_dir)
        result2 = rm2.recover()
        assert result2.recovered is True
        assert result2.from_snapshot is True
        assert result2.snapshot_id == 0
        assert result2.crash_detected is True
        assert result2.state.tasks.get("t-100", {}).get("title") == "Checkpoint task"
        assert result2.recovery_time_ms < 5000, f"Recovery too slow: {result2.recovery_time_ms}ms"
        print("  PASS")

        # === Test 10: Clean shutdown saves final snapshot ===
        print("Test 10: Clean shutdown...")
        rm3_dir = test_dir / "t10"
        rm3 = RecoveryManager(rm3_dir)
        rm3.recover()  # init
        rm3.current_state = SystemState(
            timestamp=time.time(),
            agents={"cleaner": {"status": "done"}},
            tasks={}, orchestrator={}, metrics={},
            wal_lsn=99, version=10,
        )
        rm3.shutdown()

        # Verify final snapshot was saved
        store10 = SnapshotStore(rm3_dir)
        result = store10.load_latest()
        assert result is not None
        assert result[0].wal_lsn == 99
        assert result[0].agents["cleaner"]["status"] == "done"
        assert not rm3.heartbeat.lock_path.exists(), "Lock should be released"
        print("  PASS")

        # === Test 11: SnapshotScheduler — periodic snapshots ===
        print("Test 11: Periodic snapshot scheduler...")
        rm4_dir = test_dir / "t11"
        rm4 = RecoveryManager(rm4_dir)
        rm4.recover()
        rm4.current_state = SystemState(
            timestamp=time.time(),
            agents={}, tasks={"t-sched": {"title": "Scheduled"}},
            orchestrator={}, metrics={}, wal_lsn=0, version=1,
        )

        scheduler = SnapshotScheduler(rm4, interval=0.2)  # 200ms for testing
        scheduler.start()
        time.sleep(0.8)  # wait for ~3-4 snapshots
        scheduler.stop()

        assert scheduler.snapshot_count >= 2, f"Expected >= 2 snapshots, got {scheduler.snapshot_count}"

        # Verify snapshots are on disk
        store11 = SnapshotStore(rm4_dir)
        snaps = store11.list_snapshots()
        assert len(snaps) >= 2, f"Expected >= 2 on disk, got {len(snaps)}"
        print("  PASS")

        # === Test 12: SystemState serialization round-trip ===
        print("Test 12: SystemState round-trip...")
        original = SystemState(
            timestamp=1234567890.123,
            agents={"a1": {"x": 1}, "a2": {"y": [1, 2, 3]}},
            tasks={"t-1": {"nested": {"deep": True}}},
            orchestrator={"config": {"key": "val"}},
            metrics={"float_metric": 3.14159},
            wal_lsn=999,
            version=42,
            extra={"custom_field": "hello"},
        )
        d = original.to_dict()
        restored = SystemState.from_dict(d)
        assert restored.timestamp == original.timestamp
        assert restored.agents == original.agents
        assert restored.tasks == original.tasks
        assert restored.wal_lsn == original.wal_lsn
        assert restored.version == original.version
        assert restored.extra == original.extra
        print("  PASS")

        # === Test 13: Empty state recovery ===
        print("Test 13: Empty state recovery...")
        empty = SystemState.empty()
        assert empty.agents == {}
        assert empty.tasks == {}
        assert empty.wal_lsn == -1
        assert empty.version == 0

        rm5 = RecoveryManager(test_dir / "t13_empty")
        result = rm5.recover()
        assert result.recovered is True
        assert result.from_snapshot is False
        rm5.shutdown()
        print("  PASS")

        # === Test 14: Snapshot compression ratio ===
        print("Test 14: Compression effectiveness...")
        store14 = SnapshotStore(test_dir / "t14")
        large_state = SystemState(
            timestamp=time.time(),
            agents={f"agent_{i}": {"status": "running", "config": {"param": "value" * 100}} for i in range(50)},
            tasks={f"t-{i}": {"title": f"Task {i}", "description": "x" * 500} for i in range(100)},
            orchestrator={"large_config": {f"key_{i}": "value" * 50 for i in range(10)}},
            metrics={f"metric_{i}": i * 1.5 for i in range(200)},
            wal_lsn=5000,
            version=99,
        )
        meta14 = store14.save(large_state)
        ratio = meta14.compressed_bytes / meta14.size_bytes
        assert ratio < 0.5, f"Compression ratio {ratio:.2f} should be < 0.5"

        # Verify it loads back correctly
        loaded = store14.load_latest()
        assert loaded is not None
        assert len(loaded[0].agents) == 50
        assert len(loaded[0].tasks) == 100
        print(f"  PASS (compression ratio: {ratio:.2%})")

        # === Test 15: Recovery log audit trail ===
        print("Test 15: Recovery log audit trail...")
        rm6_dir = test_dir / "t15"
        rm6 = RecoveryManager(rm6_dir)
        rm6.recover()
        rm6.current_state = SystemState.empty()
        rm6.take_snapshot()
        rm6.shutdown()

        log_path = rm6_dir / "recovery_log.jsonl"
        assert log_path.exists(), "Recovery log should exist"
        with open(log_path) as f:
            lines = [json.loads(l) for l in f if l.strip()]
        events = [l["event"] for l in lines]
        assert "recovery_complete" in events, f"Missing recovery_complete in {events}"
        assert "snapshot_taken" in events, f"Missing snapshot_taken in {events}"
        assert "shutdown" in events, f"Missing shutdown in {events}"
        print("  PASS")

        # === Test 16: Concurrent snapshot safety ===
        print("Test 16: Concurrent snapshot writes...")
        rm7_dir = test_dir / "t16"
        rm7 = RecoveryManager(rm7_dir)
        rm7.recover()
        errors: list[Exception] = []

        def snap_writer(idx: int):
            try:
                for j in range(5):
                    s = SystemState(
                        timestamp=time.time(),
                        agents={f"thread_{idx}": {"iter": j}},
                        tasks={}, orchestrator={}, metrics={},
                        wal_lsn=idx * 100 + j, version=idx,
                    )
                    rm7.take_snapshot(s)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=snap_writer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent snapshot errors: {errors}"
        # At least some snapshots should have been saved
        store16 = SnapshotStore(rm7_dir)
        snaps = store16.list_snapshots()
        assert len(snaps) > 0, "Should have snapshots after concurrent writes"
        # All remaining should be valid
        total, valid, corrupted = store16.verify_all()
        assert valid == total, f"Corrupted after concurrent writes: {corrupted}"
        print("  PASS")

        # === Test 17: Recovery speed benchmark ===
        print("Test 17: Recovery speed benchmark...")
        bench_dir = test_dir / "t17"
        rm8 = RecoveryManager(bench_dir)
        rm8.recover()

        # Save a moderately sized state
        bench_state = SystemState(
            timestamp=time.time(),
            agents={f"a_{i}": {"data": "x" * 200} for i in range(20)},
            tasks={f"t_{i}": {"title": f"Task {i}", "body": "y" * 300} for i in range(50)},
            orchestrator={"config": {f"setting_{i}": "value" for i in range(5)}},
            metrics={f"m_{i}": i for i in range(100)},
            wal_lsn=500,
            version=10,
        )
        rm8.take_snapshot(bench_state)
        rm8.heartbeat.stop()

        # Measure recovery time
        times = []
        for _ in range(5):
            rm_bench = RecoveryManager(bench_dir)
            result = rm_bench.recover()
            times.append(result.recovery_time_ms)
            rm_bench.heartbeat.stop()

        avg_ms = sum(times) / len(times)
        assert avg_ms < 500, f"Average recovery too slow: {avg_ms:.1f}ms (target <500ms)"
        print(f"  PASS (avg recovery: {avg_ms:.1f}ms)")

        print(f"\nAll 17 tests passed. Snapshot recovery system verified.")

    finally:
        shutil.rmtree(test_dir, ignore_errors=True)
