"""
Multi-Tenant SaaS Data Layer
Shared-table approach with Row Level Security (RLS) simulation.
"""

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Tenant context (thread-local) – simulates RLS by binding every query to a
# tenant_id that the caller cannot bypass.
# ---------------------------------------------------------------------------

_tenant_ctx: threading.local = threading.local()


def set_current_tenant(tenant_id: str) -> None:
    _tenant_ctx.tenant_id = tenant_id


def get_current_tenant() -> str:
    tid = getattr(_tenant_ctx, "tenant_id", None)
    if tid is None:
        raise PermissionError("No tenant context set. Call set_current_tenant() first.")
    return tid


def clear_current_tenant() -> None:
    _tenant_ctx.tenant_id = None


@contextmanager
def tenant_scope(tenant_id: str):
    prev = getattr(_tenant_ctx, "tenant_id", None)
    set_current_tenant(tenant_id)
    try:
        yield tenant_id
    finally:
        _tenant_ctx.tenant_id = prev


# ---------------------------------------------------------------------------
# Database bootstrap
# ---------------------------------------------------------------------------

def _bootstrap(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tenants (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            plan        TEXT NOT NULL DEFAULT 'free',
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id          TEXT PRIMARY KEY,
            tenant_id   TEXT NOT NULL REFERENCES tenants(id),
            email       TEXT NOT NULL,
            role        TEXT NOT NULL DEFAULT 'member',
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);

        CREATE TABLE IF NOT EXISTS projects (
            id          TEXT PRIMARY KEY,
            tenant_id   TEXT NOT NULL REFERENCES tenants(id),
            name        TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_projects_tenant ON projects(tenant_id);

        CREATE TABLE IF NOT EXISTS audit_log (
            id          TEXT PRIMARY KEY,
            tenant_id   TEXT NOT NULL REFERENCES tenants(id),
            actor_id    TEXT,
            action      TEXT NOT NULL,
            entity_type TEXT,
            entity_id   TEXT,
            detail      TEXT,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log(tenant_id);
    """)


# ---------------------------------------------------------------------------
# RLS-enforced repository layer
# ---------------------------------------------------------------------------

class TenantRepository:
    """CRUD operations that always filter by the current tenant context."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._conn.row_factory = sqlite3.Row

    # -- helpers -------------------------------------------------------------

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _uid(self) -> str:
        return uuid.uuid4().hex[:12]

    def _audit(self, action: str, entity_type: str, entity_id: str,
               detail: str = "", actor_id: str = "") -> None:
        tid = get_current_tenant()
        self._conn.execute(
            "INSERT INTO audit_log (id, tenant_id, actor_id, action, entity_type, entity_id, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (self._uid(), tid, actor_id, action, entity_type, entity_id, detail, self._now()),
        )

    # -- tenants -------------------------------------------------------------

    def create_tenant(self, name: str, plan: str = "free") -> dict:
        tid = self._uid()
        now = self._now()
        self._conn.execute(
            "INSERT INTO tenants (id, name, plan, created_at) VALUES (?, ?, ?, ?)",
            (tid, name, plan, now),
        )
        self._conn.commit()
        return {"id": tid, "name": name, "plan": plan, "created_at": now}

    def get_tenant(self, tenant_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM tenants WHERE id = ?", (tenant_id,)
        ).fetchone()
        return dict(row) if row else None

    # -- users (RLS-enforced) ------------------------------------------------

    def create_user(self, email: str, role: str = "member") -> dict:
        tid = get_current_tenant()
        uid = self._uid()
        now = self._now()
        self._conn.execute(
            "INSERT INTO users (id, tenant_id, email, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (uid, tid, email, role, now),
        )
        self._audit("create_user", "user", uid, f"email={email}", uid)
        self._conn.commit()
        return {"id": uid, "tenant_id": tid, "email": email, "role": role, "created_at": now}

    def list_users(self) -> list[dict]:
        tid = get_current_tenant()
        rows = self._conn.execute(
            "SELECT * FROM users WHERE tenant_id = ?", (tid,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_user(self, user_id: str) -> Optional[dict]:
        tid = get_current_tenant()
        row = self._conn.execute(
            "SELECT * FROM users WHERE id = ? AND tenant_id = ?", (user_id, tid)
        ).fetchone()
        return dict(row) if row else None

    def delete_user(self, user_id: str) -> bool:
        tid = get_current_tenant()
        cur = self._conn.execute(
            "DELETE FROM users WHERE id = ? AND tenant_id = ?", (user_id, tid)
        )
        if cur.rowcount:
            self._audit("delete_user", "user", user_id)
            self._conn.commit()
            return True
        return False

    # -- projects (RLS-enforced) ---------------------------------------------

    def create_project(self, name: str) -> dict:
        tid = get_current_tenant()
        pid = self._uid()
        now = self._now()
        self._conn.execute(
            "INSERT INTO projects (id, tenant_id, name, created_at) VALUES (?, ?, ?, ?)",
            (pid, tid, name, now),
        )
        self._audit("create_project", "project", pid, f"name={name}")
        self._conn.commit()
        return {"id": pid, "tenant_id": tid, "name": name, "created_at": now}

    def list_projects(self) -> list[dict]:
        tid = get_current_tenant()
        rows = self._conn.execute(
            "SELECT * FROM projects WHERE tenant_id = ?", (tid,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_project(self, project_id: str) -> Optional[dict]:
        tid = get_current_tenant()
        row = self._conn.execute(
            "SELECT * FROM projects WHERE id = ? AND tenant_id = ?", (project_id, tid)
        ).fetchone()
        return dict(row) if row else None

    def delete_project(self, project_id: str) -> bool:
        tid = get_current_tenant()
        cur = self._conn.execute(
            "DELETE FROM projects WHERE id = ? AND tenant_id = ?", (project_id, tid)
        )
        if cur.rowcount:
            self._audit("delete_project", "project", project_id)
            self._conn.commit()
            return True
        return False

    # -- audit (RLS-enforced, read-only) -------------------------------------

    def list_audit_log(self, limit: int = 50) -> list[dict]:
        tid = get_current_tenant()
        rows = self._conn.execute(
            "SELECT * FROM audit_log WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
            (tid, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- cross-tenant admin (no RLS — for platform operators only) -----------

    def admin_count_rows(self, table: str) -> int:
        if table not in ("tenants", "users", "projects", "audit_log"):
            raise ValueError(f"Unknown table: {table}")
        row = self._conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()
        return row["cnt"]


# ---------------------------------------------------------------------------
# Tenant-aware middleware simulation
# ---------------------------------------------------------------------------

class TenantMiddleware:
    """Simulates HTTP middleware that extracts tenant from a request header
    and sets the thread-local context."""

    def __init__(self, repo: TenantRepository):
        self._repo = repo

    @contextmanager
    def request(self, headers: dict[str, str]):
        tenant_id = headers.get("X-Tenant-ID")
        if not tenant_id:
            raise PermissionError("Missing X-Tenant-ID header")
        tenant = self._repo.get_tenant(tenant_id)
        if tenant is None:
            raise PermissionError(f"Unknown tenant: {tenant_id}")
        with tenant_scope(tenant_id):
            yield tenant


# ---------------------------------------------------------------------------
# Plan-based quota enforcement
# ---------------------------------------------------------------------------

PLAN_LIMITS: dict[str, dict[str, int]] = {
    "free":       {"max_users": 5,   "max_projects": 3},
    "starter":    {"max_users": 25,  "max_projects": 20},
    "business":   {"max_users": 100, "max_projects": 100},
    "enterprise": {"max_users": 999_999, "max_projects": 999_999},
}


class QuotaEnforcer:
    def __init__(self, repo: TenantRepository):
        self._repo = repo

    def check_user_quota(self) -> None:
        tid = get_current_tenant()
        tenant = self._repo.get_tenant(tid)
        if tenant is None:
            raise PermissionError("Tenant not found")
        limits = PLAN_LIMITS.get(tenant["plan"], PLAN_LIMITS["free"])
        current = len(self._repo.list_users())
        if current >= limits["max_users"]:
            raise PermissionError(
                f"User limit reached ({limits['max_users']}) for plan '{tenant['plan']}'"
            )

    def check_project_quota(self) -> None:
        tid = get_current_tenant()
        tenant = self._repo.get_tenant(tid)
        if tenant is None:
            raise PermissionError("Tenant not found")
        limits = PLAN_LIMITS.get(tenant["plan"], PLAN_LIMITS["free"])
        current = len(self._repo.list_projects())
        if current >= limits["max_projects"]:
            raise PermissionError(
                f"Project limit reached ({limits['max_projects']}) for plan '{tenant['plan']}'"
            )


# ---------------------------------------------------------------------------
# Main — end-to-end assertions
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    conn = sqlite3.connect(":memory:")
    _bootstrap(conn)
    repo = TenantRepository(conn)
    middleware = TenantMiddleware(repo)
    quota = QuotaEnforcer(repo)

    # ---- create two tenants ------------------------------------------------
    t_acme = repo.create_tenant("Acme Corp", plan="starter")
    t_globex = repo.create_tenant("Globex Inc", plan="free")
    assert t_acme["name"] == "Acme Corp"
    assert t_globex["plan"] == "free"

    # ---- populate Acme -----------------------------------------------------
    with tenant_scope(t_acme["id"]):
        u1 = repo.create_user("alice@acme.com", role="admin")
        u2 = repo.create_user("bob@acme.com")
        p1 = repo.create_project("Project Alpha")
        p2 = repo.create_project("Project Beta")

        assert len(repo.list_users()) == 2
        assert len(repo.list_projects()) == 2
        assert repo.get_user(u1["id"])["email"] == "alice@acme.com"
        assert repo.get_project(p1["id"])["name"] == "Project Alpha"

    # ---- populate Globex ---------------------------------------------------
    with tenant_scope(t_globex["id"]):
        u3 = repo.create_user("carol@globex.com", role="admin")
        p3 = repo.create_project("Project Gamma")

        assert len(repo.list_users()) == 1
        assert len(repo.list_projects()) == 1

    # ---- RLS isolation: Globex cannot see Acme data ------------------------
    with tenant_scope(t_globex["id"]):
        assert repo.get_user(u1["id"]) is None, "Globex must not see Acme user"
        assert repo.get_user(u2["id"]) is None
        assert repo.get_project(p1["id"]) is None, "Globex must not see Acme project"
        assert repo.get_project(p2["id"]) is None

    # ---- RLS isolation: Acme cannot see Globex data ------------------------
    with tenant_scope(t_acme["id"]):
        assert repo.get_user(u3["id"]) is None, "Acme must not see Globex user"
        assert repo.get_project(p3["id"]) is None, "Acme must not see Globex project"

    # ---- cross-tenant delete is a no-op ------------------------------------
    with tenant_scope(t_globex["id"]):
        assert repo.delete_user(u1["id"]) is False, "Globex cannot delete Acme user"
        assert repo.delete_project(p1["id"]) is False

    # ---- same-tenant delete works ------------------------------------------
    with tenant_scope(t_acme["id"]):
        assert repo.delete_user(u2["id"]) is True
        assert repo.get_user(u2["id"]) is None
        assert len(repo.list_users()) == 1

    # ---- audit log is tenant-scoped ----------------------------------------
    with tenant_scope(t_acme["id"]):
        acme_log = repo.list_audit_log()
        assert len(acme_log) >= 3  # create_user x2, create_project x2, delete_user
        assert all(e["tenant_id"] == t_acme["id"] for e in acme_log)

    with tenant_scope(t_globex["id"]):
        globex_log = repo.list_audit_log()
        assert all(e["tenant_id"] == t_globex["id"] for e in globex_log)

    # ---- middleware simulation ---------------------------------------------
    with middleware.request({"X-Tenant-ID": t_acme["id"]}) as tenant:
        assert tenant["name"] == "Acme Corp"
        assert len(repo.list_users()) == 1  # only alice remains

    try:
        with middleware.request({}):
            pass
        assert False, "Should have raised on missing header"
    except PermissionError:
        pass

    try:
        with middleware.request({"X-Tenant-ID": "nonexistent"}):
            pass
        assert False, "Should have raised on unknown tenant"
    except PermissionError:
        pass

    # ---- no tenant context raises ------------------------------------------
    clear_current_tenant()
    try:
        repo.list_users()
        assert False, "Should have raised without tenant context"
    except PermissionError:
        pass

    # ---- quota enforcement -------------------------------------------------
    with tenant_scope(t_globex["id"]):
        # free plan: max 3 projects
        repo.create_project("P2")
        repo.create_project("P3")
        assert len(repo.list_projects()) == 3
        try:
            quota.check_project_quota()
            assert False, "Should have raised quota error"
        except PermissionError as e:
            assert "Project limit reached" in str(e)

        # free plan: max 5 users — currently 1, add 4 more
        for i in range(4):
            quota.check_user_quota()
            repo.create_user(f"user{i}@globex.com")
        assert len(repo.list_users()) == 5
        try:
            quota.check_user_quota()
            assert False, "Should have raised user quota error"
        except PermissionError as e:
            assert "User limit reached" in str(e)

    # ---- admin cross-tenant counts -----------------------------------------
    assert repo.admin_count_rows("tenants") == 2
    assert repo.admin_count_rows("users") == 6   # 1 acme + 5 globex
    assert repo.admin_count_rows("projects") == 5  # 2 acme + 3 globex

    # ---- tenant scope nesting restores previous context --------------------
    with tenant_scope(t_acme["id"]):
        assert get_current_tenant() == t_acme["id"]
        with tenant_scope(t_globex["id"]):
            assert get_current_tenant() == t_globex["id"]
        assert get_current_tenant() == t_acme["id"], "Must restore outer tenant"

    print("All assertions passed.")
