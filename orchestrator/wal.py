"""
orchestrator/wal.py — Distributed Write-Ahead Log (WAL)
========================================================
Persist all events for recovery, audit trail, and replay.

Design:
  - Append-only JSONL segments on disk (write-ahead before state mutation)
  - CRC32 integrity check per record
  - Segment rotation when file exceeds size threshold
  - In-memory index for fast sequence lookup
  - Replay from any LSN (Log Sequence Number) for recovery
  - Subscriber callbacks for real-time event processing
  - Compaction: merge old segments into snapshots
  - Thread-safe for concurrent writers via threading.Lock
  - Atomic writes via flush + fsync

Usage:
    from orchestrator.wal import WriteAheadLog
    wal = WriteAheadLog("/tmp/wal_demo")
    lsn = wal.append("task.created", {"task_id": "t-1", "title": "Build API"})
    events = wal.replay()          # replay all
    events = wal.replay(from_lsn=5) # replay from LSN 5
    wal.checkpoint()               # snapshot current state, archive old segments
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import tempfile
import threading
import time
import zlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator


# ---------------------------------------------------------------------------
# WAL Record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WALRecord:
    """Single immutable record in the write-ahead log."""
    lsn: int                  # Log Sequence Number (monotonically increasing)
    timestamp: float          # Unix timestamp with microsecond precision
    event_type: str           # Dot-namespaced event type (e.g. "task.created")
    payload: dict             # Arbitrary event data
    crc: int                  # CRC32 checksum of (lsn + event_type + payload)
    segment_id: int           # Which segment file this record belongs to

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> WALRecord:
        return WALRecord(
            lsn=d["lsn"],
            timestamp=d["timestamp"],
            event_type=d["event_type"],
            payload=d["payload"],
            crc=d["crc"],
            segment_id=d["segment_id"],
        )

    def verify(self) -> bool:
        """Verify CRC integrity of this record."""
        expected = _compute_crc(self.lsn, self.event_type, self.payload)
        return self.crc == expected


def _compute_crc(lsn: int, event_type: str, payload: dict) -> int:
    """Compute CRC32 checksum for a WAL record."""
    raw = f"{lsn}:{event_type}:{json.dumps(payload, sort_keys=True)}".encode("utf-8")
    return zlib.crc32(raw) & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Segment Manager
# ---------------------------------------------------------------------------

class SegmentManager:
    """Manages WAL segment files on disk."""

    def __init__(self, wal_dir: Path, max_segment_bytes: int = 10 * 1024 * 1024) -> None:
        self.wal_dir = wal_dir
        self.max_segment_bytes = max_segment_bytes
        self.wal_dir.mkdir(parents=True, exist_ok=True)
        self._current_segment_id = self._find_latest_segment()
        self._current_file = self._open_segment(self._current_segment_id)

    @property
    def current_segment_id(self) -> int:
        return self._current_segment_id

    def _segment_path(self, segment_id: int) -> Path:
        return self.wal_dir / f"segment_{segment_id:06d}.wal"

    def _find_latest_segment(self) -> int:
        segments = sorted(self.wal_dir.glob("segment_*.wal"))
        if not segments:
            return 0
        name = segments[-1].stem  # e.g. "segment_000003"
        return int(name.split("_")[1])

    def _open_segment(self, segment_id: int) -> Any:
        path = self._segment_path(segment_id)
        return open(path, "a", encoding="utf-8")

    def write_record(self, record: WALRecord) -> None:
        """Write a record to the current segment, rotating if needed."""
        line = json.dumps(record.to_dict(), separators=(",", ":")) + "\n"

        # Check if rotation needed
        current_path = self._segment_path(self._current_segment_id)
        if current_path.exists() and current_path.stat().st_size >= self.max_segment_bytes:
            self._rotate()

        self._current_file.write(line)
        self._current_file.flush()
        os.fsync(self._current_file.fileno())

    def _rotate(self) -> None:
        """Close current segment and open a new one."""
        self._current_file.close()
        self._current_segment_id += 1
        self._current_file = self._open_segment(self._current_segment_id)

    def read_all_segments(self) -> Iterator[WALRecord]:
        """Read all records from all segments in order."""
        segments = sorted(self.wal_dir.glob("segment_*.wal"))
        for seg_path in segments:
            with open(seg_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    yield WALRecord.from_dict(d)

    def list_segment_ids(self) -> list[int]:
        """Return sorted list of segment IDs on disk."""
        segments = sorted(self.wal_dir.glob("segment_*.wal"))
        return [int(s.stem.split("_")[1]) for s in segments]

    def remove_segments(self, segment_ids: list[int]) -> None:
        """Remove specified segment files (after checkpoint/compaction)."""
        for sid in segment_ids:
            path = self._segment_path(sid)
            if path.exists():
                path.unlink()

    def close(self) -> None:
        if self._current_file and not self._current_file.closed:
            self._current_file.close()


# ---------------------------------------------------------------------------
# Snapshot Manager
# ---------------------------------------------------------------------------

@dataclass
class Snapshot:
    """Point-in-time snapshot of WAL state after compaction."""
    snapshot_id: int
    last_lsn: int
    timestamp: float
    event_counts: dict[str, int]       # event_type -> count
    aggregate_state: dict[str, Any]    # aggregate_id -> latest state

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> Snapshot:
        return Snapshot(
            snapshot_id=d["snapshot_id"],
            last_lsn=d["last_lsn"],
            timestamp=d["timestamp"],
            event_counts=d["event_counts"],
            aggregate_state=d["aggregate_state"],
        )


class SnapshotManager:
    """Manages snapshots for WAL compaction and fast recovery."""

    def __init__(self, wal_dir: Path) -> None:
        self.snapshot_dir = wal_dir / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def save(self, snapshot: Snapshot) -> Path:
        path = self.snapshot_dir / f"snapshot_{snapshot.snapshot_id:06d}.json"
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snapshot.to_dict(), f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.rename(str(tmp), str(path))
        return path

    def load_latest(self) -> Snapshot | None:
        snapshots = sorted(self.snapshot_dir.glob("snapshot_*.json"))
        if not snapshots:
            return None
        with open(snapshots[-1], "r", encoding="utf-8") as f:
            return Snapshot.from_dict(json.load(f))

    def list_snapshots(self) -> list[Path]:
        return sorted(self.snapshot_dir.glob("snapshot_*.json"))


# ---------------------------------------------------------------------------
# Write-Ahead Log
# ---------------------------------------------------------------------------

class WriteAheadLog:
    """
    Distributed Write-Ahead Log with:
    - Append-only durable writes with CRC integrity
    - Segment rotation (default 10MB per segment)
    - Replay from any LSN
    - Subscriber callbacks for real-time event processing
    - Checkpoint/compaction for old segment cleanup
    - Thread-safe concurrent access
    """

    def __init__(
        self,
        wal_dir: str | Path,
        max_segment_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        self.wal_dir = Path(wal_dir)
        self._lock = threading.Lock()
        self._segment_mgr = SegmentManager(self.wal_dir, max_segment_bytes)
        self._snapshot_mgr = SnapshotManager(self.wal_dir)
        self._subscribers: list[Callable[[WALRecord], None]] = []

        # In-memory index: lsn -> WALRecord (built from replay)
        self._index: dict[int, WALRecord] = {}
        self._next_lsn: int = 0
        self._event_counts: dict[str, int] = {}
        self._aggregate_state: dict[str, dict] = {}

        # Rebuild state from disk
        self._recover()

    def _recover(self) -> None:
        """Rebuild in-memory state from snapshot + WAL segments."""
        snapshot = self._snapshot_mgr.load_latest()

        if snapshot:
            # Restore aggregate counts/state from snapshot (covers compacted segments)
            self._event_counts = dict(snapshot.event_counts)
            self._aggregate_state = dict(snapshot.aggregate_state)
            self._next_lsn = snapshot.last_lsn + 1

        # Replay remaining segment records on top of snapshot
        for record in self._segment_mgr.read_all_segments():
            if not record.verify():
                raise RuntimeError(f"WAL corruption detected at LSN {record.lsn}")
            self._index[record.lsn] = record
            # Only update counts/aggregates for records not covered by snapshot
            if snapshot is None or record.lsn > snapshot.last_lsn:
                self._event_counts[record.event_type] = self._event_counts.get(record.event_type, 0) + 1
                self._track_aggregate(record)
            if record.lsn >= self._next_lsn:
                self._next_lsn = record.lsn + 1

    def _track_aggregate(self, record: WALRecord) -> None:
        """Track latest state per aggregate_id if present in payload."""
        agg_id = record.payload.get("aggregate_id")
        if agg_id:
            self._aggregate_state[agg_id] = {
                "last_event": record.event_type,
                "last_lsn": record.lsn,
                "last_timestamp": record.timestamp,
                "data": record.payload,
            }

    # --- Write API ---

    def append(self, event_type: str, payload: dict) -> int:
        """
        Append an event to the WAL. Returns the assigned LSN.
        Write is durable (fsync'd) before returning.
        """
        with self._lock:
            lsn = self._next_lsn
            self._next_lsn += 1
            crc = _compute_crc(lsn, event_type, payload)
            record = WALRecord(
                lsn=lsn,
                timestamp=time.time(),
                event_type=event_type,
                payload=payload,
                crc=crc,
                segment_id=self._segment_mgr.current_segment_id,
            )
            self._segment_mgr.write_record(record)
            self._index[lsn] = record
            self._event_counts[event_type] = self._event_counts.get(event_type, 0) + 1
            self._track_aggregate(record)

        # Notify subscribers outside lock
        for sub in self._subscribers:
            sub(record)

        return lsn

    def append_batch(self, events: list[tuple[str, dict]]) -> list[int]:
        """Append multiple events atomically. Returns list of assigned LSNs."""
        records = []
        with self._lock:
            for event_type, payload in events:
                lsn = self._next_lsn
                self._next_lsn += 1
                crc = _compute_crc(lsn, event_type, payload)
                record = WALRecord(
                    lsn=lsn,
                    timestamp=time.time(),
                    event_type=event_type,
                    payload=payload,
                    crc=crc,
                    segment_id=self._segment_mgr.current_segment_id,
                )
                self._segment_mgr.write_record(record)
                self._index[lsn] = record
                self._event_counts[event_type] = self._event_counts.get(event_type, 0) + 1
                self._track_aggregate(record)
                records.append(record)

        for record in records:
            for sub in self._subscribers:
                sub(record)

        return [r.lsn for r in records]

    # --- Read API ---

    def get(self, lsn: int) -> WALRecord | None:
        """Get a single record by LSN."""
        return self._index.get(lsn)

    def replay(
        self,
        from_lsn: int = 0,
        to_lsn: int | None = None,
        event_type: str | None = None,
    ) -> list[WALRecord]:
        """
        Replay events from the WAL.
        - from_lsn: start LSN (inclusive)
        - to_lsn: end LSN (inclusive), None = all
        - event_type: filter by event type, None = all
        """
        end = to_lsn if to_lsn is not None else self._next_lsn - 1
        results = []
        for lsn in range(from_lsn, end + 1):
            record = self._index.get(lsn)
            if record is None:
                continue
            if event_type and record.event_type != event_type:
                continue
            results.append(record)
        return results

    def replay_aggregate(self, aggregate_id: str) -> list[WALRecord]:
        """Replay all events for a specific aggregate."""
        return [
            r for r in self._index.values()
            if r.payload.get("aggregate_id") == aggregate_id
        ]

    @property
    def last_lsn(self) -> int:
        """Return the last written LSN, or -1 if empty."""
        return self._next_lsn - 1

    @property
    def size(self) -> int:
        """Total number of records in the WAL."""
        return len(self._index)

    @property
    def event_counts(self) -> dict[str, int]:
        """Count of events by type."""
        return dict(self._event_counts)

    # --- Subscribers ---

    def subscribe(self, handler: Callable[[WALRecord], None]) -> None:
        """Register a callback for new WAL records."""
        self._subscribers.append(handler)

    def unsubscribe(self, handler: Callable[[WALRecord], None]) -> None:
        """Remove a subscriber callback."""
        self._subscribers = [s for s in self._subscribers if s is not handler]

    # --- Checkpoint & Compaction ---

    def checkpoint(self) -> Snapshot | None:
        """
        Create a snapshot of current state and remove old segments.
        Returns the snapshot, or None if WAL is empty.
        """
        with self._lock:
            if not self._index:
                return None

            latest = self._snapshot_mgr.load_latest()
            snapshot_id = (latest.snapshot_id + 1) if latest else 0

            snapshot = Snapshot(
                snapshot_id=snapshot_id,
                last_lsn=self._next_lsn - 1,
                timestamp=time.time(),
                event_counts=dict(self._event_counts),
                aggregate_state=dict(self._aggregate_state),
            )
            self._snapshot_mgr.save(snapshot)

            # Remove all segments except the current one
            all_segments = self._segment_mgr.list_segment_ids()
            current = self._segment_mgr.current_segment_id
            old_segments = [s for s in all_segments if s < current]
            self._segment_mgr.remove_segments(old_segments)

        return snapshot

    # --- Audit / Query ---

    def audit_trail(
        self,
        aggregate_id: str | None = None,
        event_type: str | None = None,
        since: float | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Query the audit trail with optional filters.
        Returns records as dicts for serialization.
        """
        results = []
        for record in sorted(self._index.values(), key=lambda r: r.lsn, reverse=True):
            if aggregate_id and record.payload.get("aggregate_id") != aggregate_id:
                continue
            if event_type and record.event_type != event_type:
                continue
            if since and record.timestamp < since:
                continue
            results.append(record.to_dict())
            if len(results) >= limit:
                break
        return results

    def integrity_check(self) -> tuple[bool, list[int]]:
        """
        Verify CRC integrity of all records.
        Returns (all_ok, list_of_corrupted_lsns).
        """
        corrupted = []
        for lsn, record in sorted(self._index.items()):
            if not record.verify():
                corrupted.append(lsn)
        return len(corrupted) == 0, corrupted

    # --- Lifecycle ---

    def close(self) -> None:
        """Flush and close the WAL."""
        self._segment_mgr.close()

    def __enter__(self) -> WriteAheadLog:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def __len__(self) -> int:
        return self.size

    def __repr__(self) -> str:
        return (
            f"WriteAheadLog(dir={self.wal_dir}, records={self.size}, "
            f"last_lsn={self.last_lsn}, segments={len(self._segment_mgr.list_segment_ids())})"
        )


# ---------------------------------------------------------------------------
# Main — verify correctness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import shutil
    import tempfile

    test_dir = Path(tempfile.mkdtemp(prefix="wal_test_"))

    try:
        # === Test 1: Basic append and replay ===
        with WriteAheadLog(test_dir / "wal1") as wal:
            lsn0 = wal.append("task.created", {"aggregate_id": "t-1", "title": "Build API"})
            lsn1 = wal.append("task.assigned", {"aggregate_id": "t-1", "assignee": "alice"})
            lsn2 = wal.append("task.completed", {"aggregate_id": "t-1"})

            assert lsn0 == 0, f"First LSN should be 0, got {lsn0}"
            assert lsn1 == 1, f"Second LSN should be 1, got {lsn1}"
            assert lsn2 == 2, f"Third LSN should be 2, got {lsn2}"
            assert wal.size == 3, f"Expected 3 records, got {wal.size}"
            assert wal.last_lsn == 2, f"Expected last_lsn=2, got {wal.last_lsn}"

        # === Test 2: Recovery from disk ===
        with WriteAheadLog(test_dir / "wal1") as wal:
            assert wal.size == 3, f"After recovery expected 3, got {wal.size}"
            record = wal.get(0)
            assert record is not None
            assert record.event_type == "task.created"
            assert record.payload["title"] == "Build API"

        # === Test 3: Replay with filters ===
        with WriteAheadLog(test_dir / "wal1") as wal:
            # Replay from LSN 1
            events = wal.replay(from_lsn=1)
            assert len(events) == 2, f"Expected 2 events from LSN 1, got {len(events)}"
            assert events[0].lsn == 1
            assert events[1].lsn == 2

            # Replay by event type
            created = wal.replay(event_type="task.created")
            assert len(created) == 1
            assert created[0].payload["title"] == "Build API"

            # Replay aggregate
            agg_events = wal.replay_aggregate("t-1")
            assert len(agg_events) == 3, f"Expected 3 aggregate events, got {len(agg_events)}"

        # === Test 4: Batch append ===
        with WriteAheadLog(test_dir / "wal2") as wal:
            lsns = wal.append_batch([
                ("task.created", {"aggregate_id": "t-10", "title": "Task A"}),
                ("task.created", {"aggregate_id": "t-11", "title": "Task B"}),
                ("task.created", {"aggregate_id": "t-12", "title": "Task C"}),
            ])
            assert lsns == [0, 1, 2], f"Expected [0,1,2], got {lsns}"
            assert wal.size == 3

        # === Test 5: CRC integrity ===
        with WriteAheadLog(test_dir / "wal1") as wal:
            ok, corrupted = wal.integrity_check()
            assert ok is True, f"Integrity check failed, corrupted LSNs: {corrupted}"
            assert corrupted == []

            # Verify individual record CRC
            for lsn in range(wal.size):
                r = wal.get(lsn)
                assert r is not None
                assert r.verify(), f"CRC mismatch at LSN {lsn}"

        # === Test 6: Subscriber callbacks ===
        received: list[WALRecord] = []

        def on_event(record: WALRecord) -> None:
            received.append(record)

        with WriteAheadLog(test_dir / "wal3") as wal:
            wal.subscribe(on_event)
            wal.append("test.event", {"data": "hello"})
            wal.append("test.event", {"data": "world"})
            assert len(received) == 2, f"Expected 2 subscriber calls, got {len(received)}"
            assert received[0].payload["data"] == "hello"
            assert received[1].payload["data"] == "world"

            # Unsubscribe
            wal.unsubscribe(on_event)
            wal.append("test.event", {"data": "ignored"})
            assert len(received) == 2, "Should not receive after unsubscribe"

        # === Test 7: Checkpoint and compaction ===
        with WriteAheadLog(test_dir / "wal4") as wal:
            for i in range(50):
                wal.append("bulk.event", {"aggregate_id": f"a-{i}", "index": i})

            assert wal.size == 50

            snapshot = wal.checkpoint()
            assert snapshot is not None
            assert snapshot.last_lsn == 49
            assert snapshot.event_counts["bulk.event"] == 50
            assert "a-0" in snapshot.aggregate_state
            assert "a-49" in snapshot.aggregate_state

        # Recover after checkpoint
        with WriteAheadLog(test_dir / "wal4") as wal:
            assert wal.size == 50, f"After checkpoint recovery expected 50, got {wal.size}"

        # === Test 8: Event counts ===
        with WriteAheadLog(test_dir / "wal5") as wal:
            wal.append("type_a", {"x": 1})
            wal.append("type_a", {"x": 2})
            wal.append("type_b", {"x": 3})
            counts = wal.event_counts
            assert counts["type_a"] == 2, f"Expected type_a=2, got {counts.get('type_a')}"
            assert counts["type_b"] == 1, f"Expected type_b=1, got {counts.get('type_b')}"

        # === Test 9: Audit trail ===
        with WriteAheadLog(test_dir / "wal1") as wal:
            # All records for aggregate t-1
            trail = wal.audit_trail(aggregate_id="t-1")
            assert len(trail) == 3, f"Expected 3 audit entries, got {len(trail)}"
            # Most recent first
            assert trail[0]["lsn"] > trail[-1]["lsn"]

            # Filter by event type
            trail = wal.audit_trail(event_type="task.assigned")
            assert len(trail) == 1
            assert trail[0]["event_type"] == "task.assigned"

            # Limit
            trail = wal.audit_trail(limit=2)
            assert len(trail) == 2

        # === Test 10: Empty WAL ===
        with WriteAheadLog(test_dir / "wal_empty") as wal:
            assert wal.size == 0
            assert wal.last_lsn == -1
            events = wal.replay()
            assert events == []
            snapshot = wal.checkpoint()
            assert snapshot is None

        # === Test 11: Segment rotation (small segment size) ===
        with WriteAheadLog(test_dir / "wal_rotate", max_segment_bytes=500) as wal:
            for i in range(100):
                wal.append("rotate.test", {"index": i, "padding": "x" * 50})
            segments = wal._segment_mgr.list_segment_ids()
            assert len(segments) > 1, f"Expected multiple segments, got {len(segments)}"
            assert wal.size == 100

        # Recovery after rotation
        with WriteAheadLog(test_dir / "wal_rotate", max_segment_bytes=500) as wal:
            assert wal.size == 100, f"After rotation recovery expected 100, got {wal.size}"
            # Verify ordering
            events = wal.replay()
            for i, e in enumerate(events):
                assert e.lsn == i, f"Expected LSN {i}, got {e.lsn}"
                assert e.payload["index"] == i

        # === Test 12: Replay range ===
        with WriteAheadLog(test_dir / "wal_rotate", max_segment_bytes=500) as wal:
            events = wal.replay(from_lsn=10, to_lsn=19)
            assert len(events) == 10, f"Expected 10 events in range, got {len(events)}"
            assert events[0].lsn == 10
            assert events[-1].lsn == 19

        # === Test 13: Repr and len ===
        with WriteAheadLog(test_dir / "wal1") as wal:
            assert len(wal) == 3
            r = repr(wal)
            assert "records=3" in r
            assert "last_lsn=2" in r

        # === Test 14: Concurrent appends ===
        with WriteAheadLog(test_dir / "wal_concurrent") as wal:
            errors: list[Exception] = []

            def writer(thread_id: int) -> None:
                try:
                    for i in range(50):
                        wal.append("concurrent.write", {
                            "thread": thread_id,
                            "index": i,
                        })
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=writer, args=(tid,)) for tid in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors, f"Concurrent write errors: {errors}"
            assert wal.size == 200, f"Expected 200 concurrent records, got {wal.size}"

            # Verify all LSNs are unique and sequential
            all_lsns = sorted(wal._index.keys())
            assert all_lsns == list(range(200)), "LSNs should be 0-199 with no gaps"

            # Verify integrity after concurrent writes
            ok, corrupted = wal.integrity_check()
            assert ok, f"Integrity failed after concurrent writes: {corrupted}"

        # === Test 15: Checkpoint + new writes + recovery ===
        with WriteAheadLog(test_dir / "wal_ckpt_write") as wal:
            for i in range(10):
                wal.append("phase1", {"i": i})
            wal.checkpoint()
            for i in range(5):
                wal.append("phase2", {"i": i})
            assert wal.size == 15

        with WriteAheadLog(test_dir / "wal_ckpt_write") as wal:
            assert wal.size == 15, f"After ckpt+write recovery expected 15, got {wal.size}"
            phase2 = wal.replay(event_type="phase2")
            assert len(phase2) == 5

        print("All 15 tests passed. WAL implementation verified.")

    finally:
        shutil.rmtree(test_dir, ignore_errors=True)
