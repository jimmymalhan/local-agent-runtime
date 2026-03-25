import sqlite3
import os
import re
import hashlib
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Migration:
    version: str
    name: str
    filepath: str
    checksum: str

    @property
    def full_name(self) -> str:
        return f"{self.version}_{self.name}"


class DBMigrate:
    MIGRATION_PATTERN = re.compile(r"^(\d+)_(.+)\.sql$")

    def __init__(self, db_path: str, migrations_dir: str = "migrations"):
        self.db_path = db_path
        self.migrations_dir = migrations_dir
        self._ensure_migrations_table()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_migrations_table(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS _migrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    sql_up TEXT NOT NULL,
                    sql_down TEXT
                )
            """)

    def _parse_migration_file(self, filepath: str) -> tuple:
        """Parse a migration file, splitting on -- DOWN marker if present."""
        content = Path(filepath).read_text()
        parts = re.split(r"^-- DOWN\s*$", content, maxsplit=1, flags=re.MULTILINE)
        sql_up = parts[0].strip()
        sql_down = parts[1].strip() if len(parts) > 1 else None
        return sql_up, sql_down

    def _checksum(self, filepath: str) -> str:
        return hashlib.sha256(Path(filepath).read_bytes()).hexdigest()[:16]

    def _discover_migrations(self) -> List[Migration]:
        migrations = []
        mdir = Path(self.migrations_dir)
        if not mdir.exists():
            return migrations
        for f in sorted(mdir.iterdir()):
            m = self.MIGRATION_PATTERN.match(f.name)
            if m:
                migrations.append(Migration(
                    version=m.group(1),
                    name=m.group(2),
                    filepath=str(f),
                    checksum=self._checksum(str(f)),
                ))
        return migrations

    def _applied_versions(self, conn: sqlite3.Connection) -> List[str]:
        rows = conn.execute(
            "SELECT version FROM _migrations ORDER BY version"
        ).fetchall()
        return [r["version"] for r in rows]

    def status(self) -> dict:
        """Return applied and pending migrations."""
        all_migrations = self._discover_migrations()
        with self._connect() as conn:
            applied = set(self._applied_versions(conn))
        applied_list = [m for m in all_migrations if m.version in applied]
        pending_list = [m for m in all_migrations if m.version not in applied]
        return {"applied": applied_list, "pending": pending_list}

    def apply(self, target_version: Optional[str] = None) -> List[str]:
        """Apply pending migrations. If target_version given, apply up to that version."""
        st = self.status()
        pending = st["pending"]
        if target_version:
            pending = [m for m in pending if m.version <= target_version]

        applied = []
        with self._connect() as conn:
            for migration in pending:
                sql_up, sql_down = self._parse_migration_file(migration.filepath)
                conn.executescript(sql_up)
                conn.execute(
                    "INSERT INTO _migrations (version, name, checksum, sql_up, sql_down) VALUES (?, ?, ?, ?, ?)",
                    (migration.version, migration.name, migration.checksum, sql_up, sql_down),
                )
                applied.append(migration.full_name)
        return applied

    def rollback(self, n: int = 1) -> List[str]:
        """Rollback the last n applied migrations in reverse order."""
        rolled_back = []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT version, name, sql_down FROM _migrations ORDER BY version DESC LIMIT ?",
                (n,),
            ).fetchall()
            for row in rows:
                sql_down = row["sql_down"]
                if not sql_down:
                    raise RuntimeError(
                        f"Migration {row['version']}_{row['name']} has no DOWN section; cannot rollback"
                    )
                conn.executescript(sql_down)
                conn.execute("DELETE FROM _migrations WHERE version = ?", (row["version"],))
                rolled_back.append(f"{row['version']}_{row['name']}")
        return rolled_back


if __name__ == "__main__":
    import tempfile
    import shutil

    # Setup temp environment
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test.db")
    mig_dir = os.path.join(tmpdir, "migrations")
    os.makedirs(mig_dir)

    # Create migration files
    Path(os.path.join(mig_dir, "001_create_users.sql")).write_text(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT);\n"
        "\n-- DOWN\n"
        "DROP TABLE users;\n"
    )
    Path(os.path.join(mig_dir, "002_create_posts.sql")).write_text(
        "CREATE TABLE posts (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), title TEXT, body TEXT);\n"
        "\n-- DOWN\n"
        "DROP TABLE posts;\n"
    )
    Path(os.path.join(mig_dir, "003_add_user_age.sql")).write_text(
        "ALTER TABLE users ADD COLUMN age INTEGER;\n"
        "\n-- DOWN\n"
        "-- SQLite doesn't support DROP COLUMN in older versions, recreate table\n"
        "CREATE TABLE users_backup (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT);\n"
        "INSERT INTO users_backup SELECT id, name, email FROM users;\n"
        "DROP TABLE users;\n"
        "ALTER TABLE users_backup RENAME TO users;\n"
    )

    migrator = DBMigrate(db_path, mig_dir)

    # 1. Status before any migrations
    st = migrator.status()
    assert len(st["applied"]) == 0, "No migrations should be applied yet"
    assert len(st["pending"]) == 3, f"Expected 3 pending, got {len(st['pending'])}"
    print("PASS: initial status — 0 applied, 3 pending")

    # 2. Apply all migrations
    applied = migrator.apply()
    assert len(applied) == 3, f"Expected 3 applied, got {len(applied)}"
    assert applied[0] == "001_create_users"
    assert applied[1] == "002_create_posts"
    assert applied[2] == "003_add_user_age"
    print(f"PASS: applied all 3 migrations: {applied}")

    # 3. Status after applying all
    st = migrator.status()
    assert len(st["applied"]) == 3
    assert len(st["pending"]) == 0
    print("PASS: status — 3 applied, 0 pending")

    # 4. Verify tables exist by inserting data
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO users (name, email, age) VALUES ('Alice', 'alice@test.com', 30)")
    conn.execute("INSERT INTO posts (user_id, title, body) VALUES (1, 'Hello', 'World')")
    conn.commit()
    row = conn.execute("SELECT name, age FROM users WHERE name='Alice'").fetchone()
    assert row == ("Alice", 30), f"Unexpected row: {row}"
    conn.close()
    print("PASS: tables exist and accept data")

    # 5. Rollback last 1 migration
    rolled = migrator.rollback(n=1)
    assert len(rolled) == 1
    assert rolled[0] == "003_add_user_age"
    print(f"PASS: rolled back 1 migration: {rolled}")

    # 6. Status after rollback
    st = migrator.status()
    assert len(st["applied"]) == 2
    assert len(st["pending"]) == 1
    assert st["pending"][0].version == "003"
    print("PASS: status — 2 applied, 1 pending")

    # 7. Verify the age column is gone (table recreated without it)
    conn = sqlite3.connect(db_path)
    cols = [info[1] for info in conn.execute("PRAGMA table_info(users)").fetchall()]
    assert "age" not in cols, f"age column should be removed, got columns: {cols}"
    conn.close()
    print("PASS: rollback correctly removed age column")

    # 8. Rollback 2 more
    rolled = migrator.rollback(n=2)
    assert len(rolled) == 2
    assert rolled[0] == "002_create_posts"
    assert rolled[1] == "001_create_users"
    print(f"PASS: rolled back 2 more: {rolled}")

    # 9. All pending again
    st = migrator.status()
    assert len(st["applied"]) == 0
    assert len(st["pending"]) == 3
    print("PASS: status — 0 applied, 3 pending (full rollback)")

    # 10. Apply up to a target version
    applied = migrator.apply(target_version="002")
    assert len(applied) == 2
    assert applied[-1] == "002_create_posts"
    st = migrator.status()
    assert len(st["pending"]) == 1
    print("PASS: partial apply up to version 002")

    # 11. Re-apply is idempotent (no duplicates)
    applied = migrator.apply(target_version="002")
    assert len(applied) == 0, "Should not re-apply already applied migrations"
    print("PASS: re-apply is idempotent")

    # Cleanup
    shutil.rmtree(tmpdir)
    print("\nAll assertions passed.")
