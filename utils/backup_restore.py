"""
Backup & Restore System (<1h RTO)

Full backup/restore lifecycle for the agent runtime:
- Incremental and full daily backups with configurable retention
- Compressed, checksummed backup archives with manifest
- Point-in-time restore with integrity verification
- Automated restore testing (daily test-restore to temp dir)
- Backup rotation and cleanup (grandfather-father-son)
- RTO tracking: every restore is timed and must complete < 1h
"""

import gzip
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_RTO_SECONDS = 3600  # 1 hour
DEFAULT_RETENTION_DAYS = 30
DEFAULT_FULL_INTERVAL_DAYS = 7  # full backup every 7 days
CHUNK_SIZE = 1 << 20  # 1 MiB read chunks
COMPRESS_LEVEL = 6


class BackupType(Enum):
    FULL = "full"
    INCREMENTAL = "incremental"


class BackupStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    VERIFIED = "verified"


class RestoreStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    VERIFIED = "verified"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class FileEntry:
    """A single file tracked in a backup."""
    rel_path: str
    size: int
    mtime: float
    sha256: str
    compressed_size: int = 0

    def to_dict(self) -> dict:
        return {
            "rel_path": self.rel_path,
            "size": self.size,
            "mtime": self.mtime,
            "sha256": self.sha256,
            "compressed_size": self.compressed_size,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FileEntry":
        return cls(**d)


@dataclass
class BackupManifest:
    """Describes a single backup snapshot."""
    backup_id: str
    backup_type: BackupType
    status: BackupStatus
    created_at: float
    completed_at: Optional[float] = None
    source_dir: str = ""
    backup_dir: str = ""
    parent_backup_id: Optional[str] = None
    files: list[FileEntry] = field(default_factory=list)
    total_size: int = 0
    compressed_total: int = 0
    file_count: int = 0
    checksum: str = ""
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "backup_id": self.backup_id,
            "backup_type": self.backup_type.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "source_dir": self.source_dir,
            "backup_dir": self.backup_dir,
            "parent_backup_id": self.parent_backup_id,
            "files": [f.to_dict() for f in self.files],
            "total_size": self.total_size,
            "compressed_total": self.compressed_total,
            "file_count": self.file_count,
            "checksum": self.checksum,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BackupManifest":
        files = [FileEntry.from_dict(f) for f in d.get("files", [])]
        return cls(
            backup_id=d["backup_id"],
            backup_type=BackupType(d["backup_type"]),
            status=BackupStatus(d["status"]),
            created_at=d["created_at"],
            completed_at=d.get("completed_at"),
            source_dir=d.get("source_dir", ""),
            backup_dir=d.get("backup_dir", ""),
            parent_backup_id=d.get("parent_backup_id"),
            files=files,
            total_size=d.get("total_size", 0),
            compressed_total=d.get("compressed_total", 0),
            file_count=d.get("file_count", 0),
            checksum=d.get("checksum", ""),
            error=d.get("error"),
        )


@dataclass
class RestoreResult:
    """Outcome of a restore operation."""
    restore_id: str
    backup_id: str
    status: RestoreStatus
    started_at: float
    completed_at: Optional[float] = None
    target_dir: str = ""
    files_restored: int = 0
    bytes_restored: int = 0
    duration_seconds: float = 0.0
    rto_met: bool = False
    integrity_ok: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "restore_id": self.restore_id,
            "backup_id": self.backup_id,
            "status": self.status.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "target_dir": self.target_dir,
            "files_restored": self.files_restored,
            "bytes_restored": self.bytes_restored,
            "duration_seconds": self.duration_seconds,
            "rto_met": self.rto_met,
            "integrity_ok": self.integrity_ok,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Checksum helpers
# ---------------------------------------------------------------------------

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_checksum(manifest: BackupManifest) -> str:
    """Deterministic checksum over all file entries in the manifest."""
    h = hashlib.sha256()
    for fe in sorted(manifest.files, key=lambda f: f.rel_path):
        h.update(fe.rel_path.encode())
        h.update(fe.sha256.encode())
        h.update(str(fe.size).encode())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Compression helpers
# ---------------------------------------------------------------------------

def compress_file(src: str, dst: str) -> int:
    """Gzip-compress src to dst. Returns compressed size."""
    with open(src, "rb") as fin, gzip.open(dst, "wb", compresslevel=COMPRESS_LEVEL) as fout:
        shutil.copyfileobj(fin, fout, CHUNK_SIZE)
    return os.path.getsize(dst)


def decompress_file(src: str, dst: str) -> int:
    """Decompress gzipped src to dst. Returns decompressed size."""
    with gzip.open(src, "rb") as fin, open(dst, "wb") as fout:
        shutil.copyfileobj(fin, fout, CHUNK_SIZE)
    return os.path.getsize(dst)


# ---------------------------------------------------------------------------
# Backup catalog
# ---------------------------------------------------------------------------

class BackupCatalog:
    """Persistent catalog of all backups, stored as JSON."""

    def __init__(self, catalog_path: str):
        self.catalog_path = catalog_path
        self._lock = threading.Lock()
        self._manifests: dict[str, BackupManifest] = {}
        self._load()

    def _load(self):
        if os.path.exists(self.catalog_path):
            with open(self.catalog_path, "r") as f:
                data = json.load(f)
            for entry in data.get("backups", []):
                m = BackupManifest.from_dict(entry)
                self._manifests[m.backup_id] = m

    def _save(self):
        data = {
            "backups": [m.to_dict() for m in self._manifests.values()],
            "updated_at": time.time(),
        }
        tmp = self.catalog_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.catalog_path)

    def add(self, manifest: BackupManifest):
        with self._lock:
            self._manifests[manifest.backup_id] = manifest
            self._save()

    def update(self, manifest: BackupManifest):
        self.add(manifest)

    def get(self, backup_id: str) -> Optional[BackupManifest]:
        return self._manifests.get(backup_id)

    def latest(self, backup_type: Optional[BackupType] = None) -> Optional[BackupManifest]:
        candidates = [
            m for m in self._manifests.values()
            if m.status in (BackupStatus.COMPLETED, BackupStatus.VERIFIED)
        ]
        if backup_type:
            candidates = [m for m in candidates if m.backup_type == backup_type]
        if not candidates:
            return None
        return max(candidates, key=lambda m: m.created_at)

    def list_all(self) -> list[BackupManifest]:
        return sorted(self._manifests.values(), key=lambda m: m.created_at, reverse=True)

    def remove(self, backup_id: str):
        with self._lock:
            self._manifests.pop(backup_id, None)
            self._save()

    def expired(self, retention_days: int) -> list[BackupManifest]:
        cutoff = time.time() - retention_days * 86400
        return [
            m for m in self._manifests.values()
            if m.created_at < cutoff and m.status != BackupStatus.IN_PROGRESS
        ]


# ---------------------------------------------------------------------------
# Backup engine
# ---------------------------------------------------------------------------

class BackupEngine:
    """Creates full and incremental backups of a source directory."""

    def __init__(
        self,
        source_dir: str,
        backup_root: str,
        catalog: BackupCatalog,
        exclude_patterns: Optional[list[str]] = None,
    ):
        self.source_dir = os.path.abspath(source_dir)
        self.backup_root = os.path.abspath(backup_root)
        self.catalog = catalog
        self.exclude_patterns = exclude_patterns or [
            "__pycache__", ".git", "node_modules", ".env", "*.pyc", ".DS_Store",
        ]
        os.makedirs(self.backup_root, exist_ok=True)

    def _should_exclude(self, rel_path: str) -> bool:
        parts = Path(rel_path).parts
        for pattern in self.exclude_patterns:
            if pattern.startswith("*"):
                if rel_path.endswith(pattern[1:]):
                    return True
            elif pattern in parts or rel_path == pattern:
                return True
        return False

    def _scan_source(self) -> list[FileEntry]:
        entries = []
        for root, dirs, files in os.walk(self.source_dir):
            # prune excluded dirs in-place
            dirs[:] = [d for d in dirs if not self._should_exclude(d)]
            for fname in files:
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, self.source_dir)
                if self._should_exclude(rel):
                    continue
                try:
                    stat = os.stat(full)
                    checksum = sha256_file(full)
                    entries.append(FileEntry(
                        rel_path=rel,
                        size=stat.st_size,
                        mtime=stat.st_mtime,
                        sha256=checksum,
                    ))
                except (OSError, PermissionError):
                    continue
        return entries

    def _changed_files(
        self, current: list[FileEntry], baseline: BackupManifest
    ) -> list[FileEntry]:
        baseline_map = {f.rel_path: f for f in baseline.files}
        changed = []
        for fe in current:
            old = baseline_map.get(fe.rel_path)
            if old is None or old.sha256 != fe.sha256:
                changed.append(fe)
        return changed

    def _backup_files(
        self, files: list[FileEntry], backup_data_dir: str
    ) -> list[FileEntry]:
        backed_up = []
        for fe in files:
            src = os.path.join(self.source_dir, fe.rel_path)
            dst_rel = fe.rel_path + ".gz"
            dst = os.path.join(backup_data_dir, dst_rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                compressed_size = compress_file(src, dst)
                fe.compressed_size = compressed_size
                backed_up.append(fe)
            except (OSError, PermissionError):
                continue
        return backed_up

    def full_backup(self) -> BackupManifest:
        backup_id = f"full-{uuid.uuid4().hex[:12]}"
        manifest = BackupManifest(
            backup_id=backup_id,
            backup_type=BackupType.FULL,
            status=BackupStatus.IN_PROGRESS,
            created_at=time.time(),
            source_dir=self.source_dir,
        )
        self.catalog.add(manifest)

        backup_dir = os.path.join(self.backup_root, backup_id)
        data_dir = os.path.join(backup_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        manifest.backup_dir = backup_dir

        try:
            all_files = self._scan_source()
            backed_up = self._backup_files(all_files, data_dir)
            manifest.files = backed_up
            manifest.file_count = len(backed_up)
            manifest.total_size = sum(f.size for f in backed_up)
            manifest.compressed_total = sum(f.compressed_size for f in backed_up)
            manifest.checksum = manifest_checksum(manifest)
            manifest.status = BackupStatus.COMPLETED
            manifest.completed_at = time.time()
        except Exception as exc:
            manifest.status = BackupStatus.FAILED
            manifest.error = str(exc)
            manifest.completed_at = time.time()

        self.catalog.update(manifest)
        return manifest

    def incremental_backup(
        self, parent_id: Optional[str] = None
    ) -> BackupManifest:
        parent = None
        if parent_id:
            parent = self.catalog.get(parent_id)
        if parent is None:
            parent = self.catalog.latest(BackupType.FULL)
        if parent is None:
            return self.full_backup()

        backup_id = f"incr-{uuid.uuid4().hex[:12]}"
        manifest = BackupManifest(
            backup_id=backup_id,
            backup_type=BackupType.INCREMENTAL,
            status=BackupStatus.IN_PROGRESS,
            created_at=time.time(),
            source_dir=self.source_dir,
            parent_backup_id=parent.backup_id,
        )
        self.catalog.add(manifest)

        backup_dir = os.path.join(self.backup_root, backup_id)
        data_dir = os.path.join(backup_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        manifest.backup_dir = backup_dir

        try:
            current_files = self._scan_source()
            changed = self._changed_files(current_files, parent)
            if not changed:
                manifest.files = []
                manifest.file_count = 0
                manifest.total_size = 0
                manifest.compressed_total = 0
                manifest.checksum = manifest_checksum(manifest)
                manifest.status = BackupStatus.COMPLETED
                manifest.completed_at = time.time()
            else:
                backed_up = self._backup_files(changed, data_dir)
                manifest.files = backed_up
                manifest.file_count = len(backed_up)
                manifest.total_size = sum(f.size for f in backed_up)
                manifest.compressed_total = sum(f.compressed_size for f in backed_up)
                manifest.checksum = manifest_checksum(manifest)
                manifest.status = BackupStatus.COMPLETED
                manifest.completed_at = time.time()
        except Exception as exc:
            manifest.status = BackupStatus.FAILED
            manifest.error = str(exc)
            manifest.completed_at = time.time()

        self.catalog.update(manifest)
        return manifest


# ---------------------------------------------------------------------------
# Restore engine
# ---------------------------------------------------------------------------

class RestoreEngine:
    """Restores from backup with integrity verification and RTO tracking."""

    def __init__(self, catalog: BackupCatalog, rto_seconds: int = DEFAULT_RTO_SECONDS):
        self.catalog = catalog
        self.rto_seconds = rto_seconds

    def _resolve_chain(self, backup_id: str) -> list[BackupManifest]:
        """Walk the incremental chain back to the base full backup."""
        chain = []
        current = self.catalog.get(backup_id)
        while current:
            chain.append(current)
            if current.backup_type == BackupType.FULL:
                break
            current = self.catalog.get(current.parent_backup_id) if current.parent_backup_id else None
        chain.reverse()
        return chain

    def restore(
        self, backup_id: str, target_dir: str, verify: bool = True
    ) -> RestoreResult:
        result = RestoreResult(
            restore_id=f"restore-{uuid.uuid4().hex[:12]}",
            backup_id=backup_id,
            status=RestoreStatus.IN_PROGRESS,
            started_at=time.time(),
            target_dir=target_dir,
        )

        chain = self._resolve_chain(backup_id)
        if not chain:
            result.status = RestoreStatus.FAILED
            result.errors.append(f"Backup {backup_id} not found or broken chain")
            result.completed_at = time.time()
            result.duration_seconds = result.completed_at - result.started_at
            return result

        os.makedirs(target_dir, exist_ok=True)

        # Apply each backup in chain order (full first, then incrementals)
        file_map: dict[str, FileEntry] = {}
        for manifest in chain:
            for fe in manifest.files:
                file_map[fe.rel_path] = (fe, manifest)

        files_restored = 0
        bytes_restored = 0
        errors = []

        for rel_path, (fe, manifest) in file_map.items():
            src_gz = os.path.join(manifest.backup_dir, "data", rel_path + ".gz")
            dst = os.path.join(target_dir, rel_path)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                size = decompress_file(src_gz, dst)
                bytes_restored += size
                files_restored += 1
            except Exception as exc:
                errors.append(f"Failed to restore {rel_path}: {exc}")

        result.files_restored = files_restored
        result.bytes_restored = bytes_restored
        result.errors = errors

        # Integrity check
        if verify and not errors:
            integrity_ok = True
            for rel_path, (fe, _) in file_map.items():
                restored_path = os.path.join(target_dir, rel_path)
                if not os.path.exists(restored_path):
                    integrity_ok = False
                    result.errors.append(f"Missing after restore: {rel_path}")
                    continue
                actual_hash = sha256_file(restored_path)
                if actual_hash != fe.sha256:
                    integrity_ok = False
                    result.errors.append(
                        f"Checksum mismatch: {rel_path} "
                        f"(expected {fe.sha256[:16]}..., got {actual_hash[:16]}...)"
                    )
            result.integrity_ok = integrity_ok
        elif not errors:
            result.integrity_ok = True

        result.completed_at = time.time()
        result.duration_seconds = result.completed_at - result.started_at
        result.rto_met = result.duration_seconds < self.rto_seconds

        if result.errors:
            result.status = RestoreStatus.FAILED
        else:
            result.status = RestoreStatus.VERIFIED if verify else RestoreStatus.COMPLETED

        return result

    def test_restore(self, backup_id: Optional[str] = None) -> RestoreResult:
        """Run a test restore to a temp directory, then clean up."""
        if backup_id is None:
            latest = self.catalog.latest()
            if latest is None:
                return RestoreResult(
                    restore_id=f"test-{uuid.uuid4().hex[:12]}",
                    backup_id="none",
                    status=RestoreStatus.FAILED,
                    started_at=time.time(),
                    completed_at=time.time(),
                    errors=["No backups available for test restore"],
                )
            backup_id = latest.backup_id

        tmp_dir = tempfile.mkdtemp(prefix="backup_test_restore_")
        try:
            result = self.restore(backup_id, tmp_dir, verify=True)
            result.restore_id = f"test-{result.restore_id}"
            return result
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Retention / rotation (grandfather-father-son)
# ---------------------------------------------------------------------------

class RetentionPolicy:
    """Manages backup rotation with configurable retention."""

    def __init__(
        self,
        catalog: BackupCatalog,
        daily_keep: int = 7,
        weekly_keep: int = 4,
        monthly_keep: int = 6,
    ):
        self.catalog = catalog
        self.daily_keep = daily_keep
        self.weekly_keep = weekly_keep
        self.monthly_keep = monthly_keep

    def _bucket_key(self, ts: float, granularity: str) -> str:
        import datetime
        dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        if granularity == "daily":
            return dt.strftime("%Y-%m-%d")
        elif granularity == "weekly":
            return dt.strftime("%Y-W%W")
        else:
            return dt.strftime("%Y-%m")

    def apply(self) -> list[str]:
        """Return list of backup_ids that were removed."""
        all_backups = self.catalog.list_all()
        if not all_backups:
            return []

        keep_ids: set[str] = set()

        # Daily: keep most recent per day
        daily_buckets: dict[str, BackupManifest] = {}
        for m in all_backups:
            key = self._bucket_key(m.created_at, "daily")
            if key not in daily_buckets:
                daily_buckets[key] = m
        recent_daily = sorted(daily_buckets.keys(), reverse=True)[: self.daily_keep]
        for key in recent_daily:
            keep_ids.add(daily_buckets[key].backup_id)

        # Weekly: keep most recent per week
        weekly_buckets: dict[str, BackupManifest] = {}
        for m in all_backups:
            key = self._bucket_key(m.created_at, "weekly")
            if key not in weekly_buckets:
                weekly_buckets[key] = m
        recent_weekly = sorted(weekly_buckets.keys(), reverse=True)[: self.weekly_keep]
        for key in recent_weekly:
            keep_ids.add(weekly_buckets[key].backup_id)

        # Monthly: keep most recent per month
        monthly_buckets: dict[str, BackupManifest] = {}
        for m in all_backups:
            key = self._bucket_key(m.created_at, "monthly")
            if key not in monthly_buckets:
                monthly_buckets[key] = m
        recent_monthly = sorted(monthly_buckets.keys(), reverse=True)[: self.monthly_keep]
        for key in recent_monthly:
            keep_ids.add(monthly_buckets[key].backup_id)

        # Always keep the latest full backup
        latest_full = self.catalog.latest(BackupType.FULL)
        if latest_full:
            keep_ids.add(latest_full.backup_id)

        # Remove anything not in keep set
        removed = []
        for m in all_backups:
            if m.backup_id not in keep_ids:
                if m.backup_dir and os.path.isdir(m.backup_dir):
                    shutil.rmtree(m.backup_dir, ignore_errors=True)
                self.catalog.remove(m.backup_id)
                removed.append(m.backup_id)

        return removed


# ---------------------------------------------------------------------------
# Daily scheduler
# ---------------------------------------------------------------------------

class DailyBackupScheduler:
    """Coordinates daily backup, test-restore, and retention in one run."""

    def __init__(
        self,
        source_dir: str,
        backup_root: str,
        full_interval_days: int = DEFAULT_FULL_INTERVAL_DAYS,
        rto_seconds: int = DEFAULT_RTO_SECONDS,
    ):
        self.source_dir = source_dir
        self.backup_root = backup_root
        self.full_interval_days = full_interval_days
        catalog_path = os.path.join(backup_root, "catalog.json")
        self.catalog = BackupCatalog(catalog_path)
        self.engine = BackupEngine(source_dir, backup_root, self.catalog)
        self.restore_engine = RestoreEngine(self.catalog, rto_seconds)
        self.retention = RetentionPolicy(self.catalog)

    def _needs_full(self) -> bool:
        latest_full = self.catalog.latest(BackupType.FULL)
        if latest_full is None:
            return True
        age_days = (time.time() - latest_full.created_at) / 86400
        return age_days >= self.full_interval_days

    def run(self) -> dict[str, Any]:
        """Execute daily backup cycle: backup → test-restore → retention."""
        report: dict[str, Any] = {"timestamp": time.time()}

        # 1. Backup
        if self._needs_full():
            manifest = self.engine.full_backup()
        else:
            manifest = self.engine.incremental_backup()

        report["backup"] = {
            "id": manifest.backup_id,
            "type": manifest.backup_type.value,
            "status": manifest.status.value,
            "files": manifest.file_count,
            "size": manifest.total_size,
            "compressed": manifest.compressed_total,
            "duration": (manifest.completed_at or 0) - manifest.created_at,
        }

        # 2. Test restore
        if manifest.status == BackupStatus.COMPLETED:
            restore_result = self.restore_engine.test_restore(manifest.backup_id)
            report["test_restore"] = {
                "id": restore_result.restore_id,
                "status": restore_result.status.value,
                "files_restored": restore_result.files_restored,
                "duration": restore_result.duration_seconds,
                "rto_met": restore_result.rto_met,
                "integrity_ok": restore_result.integrity_ok,
                "errors": restore_result.errors,
            }
        else:
            report["test_restore"] = {"status": "skipped", "reason": "backup failed"}

        # 3. Retention
        removed = self.retention.apply()
        report["retention"] = {"removed_count": len(removed), "removed_ids": removed}

        return report


# ---------------------------------------------------------------------------
# __main__: verification assertions
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("Backup & Restore System — Verification Suite")
    print("=" * 70)

    # Set up temp environment
    work_dir = tempfile.mkdtemp(prefix="backup_verify_")
    source_dir = os.path.join(work_dir, "source")
    backup_root = os.path.join(work_dir, "backups")
    restore_dir = os.path.join(work_dir, "restored")
    os.makedirs(source_dir)
    os.makedirs(backup_root)

    # Create sample source files
    files_created = {}
    for name, content in [
        ("config.json", '{"version": 1, "name": "agent-runtime"}'),
        ("state/agent_stats.json", '{"executor": {"success": 373}}'),
        ("state/recovery.jsonl", '{"ts": 1}\n{"ts": 2}\n'),
        ("agents/router.py", 'def route(task): return "executor"'),
        ("agents/executor.py", 'def execute(task): return {"ok": True}'),
        ("dashboard/state.json", '{"tasks": [], "status": "idle"}'),
        ("reports/daily.log", "2026-03-27 OK\n" * 100),
    ]:
        path = os.path.join(source_dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        files_created[name] = content

    catalog = BackupCatalog(os.path.join(backup_root, "catalog.json"))
    engine = BackupEngine(source_dir, backup_root, catalog)
    restore_eng = RestoreEngine(catalog, rto_seconds=DEFAULT_RTO_SECONDS)

    # ------------------------------------------------------------------
    # Test 1: Full backup
    # ------------------------------------------------------------------
    print("\n[Test 1] Full backup...")
    full = engine.full_backup()
    assert full.status == BackupStatus.COMPLETED, f"Full backup failed: {full.error}"
    assert full.file_count == len(files_created), (
        f"Expected {len(files_created)} files, got {full.file_count}"
    )
    assert full.total_size > 0, "Total size should be > 0"
    assert full.compressed_total > 0, "Compressed total should be > 0"
    assert full.checksum, "Checksum should be set"
    assert full.completed_at is not None and full.completed_at > full.created_at
    print(f"  OK: {full.file_count} files, {full.total_size} bytes "
          f"-> {full.compressed_total} bytes compressed")

    # ------------------------------------------------------------------
    # Test 2: Full restore with integrity verification
    # ------------------------------------------------------------------
    print("\n[Test 2] Full restore + integrity check...")
    result = restore_eng.restore(full.backup_id, restore_dir, verify=True)
    assert result.status == RestoreStatus.VERIFIED, f"Restore failed: {result.errors}"
    assert result.files_restored == len(files_created)
    assert result.integrity_ok is True
    assert result.rto_met is True, (
        f"RTO not met: {result.duration_seconds:.1f}s > {DEFAULT_RTO_SECONDS}s"
    )
    assert not result.errors
    # Verify file contents match
    for name, content in files_created.items():
        restored_path = os.path.join(restore_dir, name)
        assert os.path.exists(restored_path), f"Missing: {name}"
        with open(restored_path, "r") as f:
            assert f.read() == content, f"Content mismatch: {name}"
    print(f"  OK: {result.files_restored} files restored in "
          f"{result.duration_seconds:.3f}s (RTO met: {result.rto_met})")

    # ------------------------------------------------------------------
    # Test 3: Incremental backup (no changes)
    # ------------------------------------------------------------------
    print("\n[Test 3] Incremental backup (no changes)...")
    incr_noop = engine.incremental_backup()
    assert incr_noop.status == BackupStatus.COMPLETED
    assert incr_noop.backup_type == BackupType.INCREMENTAL
    assert incr_noop.file_count == 0, "No files should have changed"
    assert incr_noop.parent_backup_id == full.backup_id
    print(f"  OK: 0 changed files (parent={full.backup_id})")

    # ------------------------------------------------------------------
    # Test 4: Incremental backup (with changes)
    # ------------------------------------------------------------------
    print("\n[Test 4] Incremental backup (with changes)...")
    # Modify one file, add a new file
    with open(os.path.join(source_dir, "config.json"), "w") as f:
        f.write('{"version": 2, "name": "agent-runtime", "updated": true}')
    new_file = os.path.join(source_dir, "state/new_metric.json")
    with open(new_file, "w") as f:
        f.write('{"metric": "latency", "value": 42}')

    incr = engine.incremental_backup()
    assert incr.status == BackupStatus.COMPLETED
    assert incr.backup_type == BackupType.INCREMENTAL
    assert incr.file_count == 2, f"Expected 2 changed files, got {incr.file_count}"
    changed_paths = {fe.rel_path for fe in incr.files}
    assert "config.json" in changed_paths
    assert os.path.join("state", "new_metric.json") in changed_paths
    print(f"  OK: {incr.file_count} changed files backed up")

    # ------------------------------------------------------------------
    # Test 5: Restore from incremental (chain resolution)
    # ------------------------------------------------------------------
    print("\n[Test 5] Restore from incremental (chain resolution)...")
    restore_dir2 = os.path.join(work_dir, "restored_incr")
    result2 = restore_eng.restore(incr.backup_id, restore_dir2, verify=True)
    assert result2.status == RestoreStatus.VERIFIED, f"Failed: {result2.errors}"
    assert result2.integrity_ok is True
    assert result2.rto_met is True
    # Check the updated config
    with open(os.path.join(restore_dir2, "config.json"), "r") as f:
        data = json.loads(f.read())
        assert data["version"] == 2
        assert data["updated"] is True
    # Check the new file
    with open(os.path.join(restore_dir2, "state", "new_metric.json"), "r") as f:
        data = json.loads(f.read())
        assert data["metric"] == "latency"
    print(f"  OK: chain restore verified, {result2.files_restored} files, "
          f"{result2.duration_seconds:.3f}s")

    # ------------------------------------------------------------------
    # Test 6: Test restore (temp dir, auto cleanup)
    # ------------------------------------------------------------------
    print("\n[Test 6] Test restore (auto cleanup)...")
    test_result = restore_eng.test_restore(full.backup_id)
    assert test_result.status == RestoreStatus.VERIFIED
    assert test_result.integrity_ok is True
    assert test_result.rto_met is True
    assert "test-" in test_result.restore_id
    print(f"  OK: test restore passed ({test_result.duration_seconds:.3f}s)")

    # ------------------------------------------------------------------
    # Test 7: Catalog persistence
    # ------------------------------------------------------------------
    print("\n[Test 7] Catalog persistence...")
    catalog_path = os.path.join(backup_root, "catalog.json")
    catalog2 = BackupCatalog(catalog_path)
    all_backups = catalog2.list_all()
    assert len(all_backups) >= 3, f"Expected >=3 backups, got {len(all_backups)}"
    latest = catalog2.latest()
    assert latest is not None
    assert latest.backup_id == incr.backup_id
    latest_full = catalog2.latest(BackupType.FULL)
    assert latest_full is not None
    assert latest_full.backup_id == full.backup_id
    print(f"  OK: catalog has {len(all_backups)} entries, latest={latest.backup_id}")

    # ------------------------------------------------------------------
    # Test 8: Retention policy
    # ------------------------------------------------------------------
    print("\n[Test 8] Retention policy...")
    retention = RetentionPolicy(catalog, daily_keep=2, weekly_keep=1, monthly_keep=1)
    removed = retention.apply()
    remaining = catalog.list_all()
    assert len(remaining) > 0, "Should keep at least latest full"
    print(f"  OK: removed {len(removed)}, kept {len(remaining)}")

    # ------------------------------------------------------------------
    # Test 9: Daily scheduler end-to-end
    # ------------------------------------------------------------------
    print("\n[Test 9] Daily scheduler end-to-end...")
    sched_source = os.path.join(work_dir, "sched_source")
    sched_backup = os.path.join(work_dir, "sched_backups")
    os.makedirs(sched_source)
    with open(os.path.join(sched_source, "data.txt"), "w") as f:
        f.write("important data\n" * 50)

    scheduler = DailyBackupScheduler(
        sched_source, sched_backup, full_interval_days=7, rto_seconds=DEFAULT_RTO_SECONDS,
    )
    report = scheduler.run()
    assert report["backup"]["status"] == "completed"
    assert report["backup"]["type"] == "full"  # first run is always full
    assert report["test_restore"]["status"] == "verified"
    assert report["test_restore"]["rto_met"] is True
    assert report["test_restore"]["integrity_ok"] is True
    print(f"  OK: scheduler report = backup:{report['backup']['status']}, "
          f"restore:{report['test_restore']['status']}, "
          f"rto_met:{report['test_restore']['rto_met']}")

    # Second run should be incremental
    report2 = scheduler.run()
    assert report2["backup"]["type"] == "incremental"
    assert report2["backup"]["status"] == "completed"
    print(f"  OK: second run = {report2['backup']['type']}")

    # ------------------------------------------------------------------
    # Test 10: Checksum tamper detection
    # ------------------------------------------------------------------
    print("\n[Test 10] Checksum tamper detection...")
    tamper_restore = os.path.join(work_dir, "tamper_test")
    # Get a fresh full backup
    sched_full = scheduler.catalog.latest(BackupType.FULL)
    assert sched_full is not None
    # Tamper with a compressed file
    tampered_file = sched_full.files[0]
    gz_path = os.path.join(sched_full.backup_dir, "data", tampered_file.rel_path + ".gz")
    with gzip.open(gz_path, "wb") as f:
        f.write(b"TAMPERED CONTENT")
    tamper_result = scheduler.restore_engine.restore(
        sched_full.backup_id, tamper_restore, verify=True
    )
    assert tamper_result.integrity_ok is False, "Should detect tampering"
    assert any("Checksum mismatch" in e for e in tamper_result.errors)
    print(f"  OK: tamper detected — {tamper_result.errors[0][:60]}...")

    # ------------------------------------------------------------------
    # Test 11: Serialization round-trip
    # ------------------------------------------------------------------
    print("\n[Test 11] Manifest serialization round-trip...")
    d = full.to_dict()
    roundtrip = BackupManifest.from_dict(d)
    assert roundtrip.backup_id == full.backup_id
    assert roundtrip.backup_type == full.backup_type
    assert roundtrip.file_count == full.file_count
    assert roundtrip.checksum == full.checksum
    assert len(roundtrip.files) == len(full.files)
    print("  OK: manifest serializes and deserializes correctly")

    # ------------------------------------------------------------------
    # Test 12: Restore of missing backup returns failure
    # ------------------------------------------------------------------
    print("\n[Test 12] Restore of missing backup...")
    missing = restore_eng.restore("nonexistent-id", os.path.join(work_dir, "nope"))
    assert missing.status == RestoreStatus.FAILED
    assert "not found" in missing.errors[0].lower()
    print(f"  OK: correctly failed — {missing.errors[0]}")

    # Cleanup
    shutil.rmtree(work_dir, ignore_errors=True)

    print("\n" + "=" * 70)
    print("ALL 12 TESTS PASSED — Backup & Restore System Verified")
    print(f"  RTO target: <{DEFAULT_RTO_SECONDS}s (1 hour)")
    print("  Features: full + incremental backups, chain restore,")
    print("            integrity verification, tamper detection,")
    print("            retention rotation, daily scheduling, test restores")
    print("=" * 70)
