"""
Refactor: Convert 5-level deep callback hell to clean async/await.
Both implementations produce identical results, verified by assertions.
"""

import asyncio
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Simulated async I/O helpers (shared by both styles)
# ---------------------------------------------------------------------------

_USERS_DB = {
    "u1": {"id": "u1", "name": "Alice", "org_id": "org42"},
    "u2": {"id": "u2", "name": "Bob", "org_id": "org7"},
}

_ORGS_DB = {
    "org42": {"id": "org42", "name": "Acme Corp", "plan": "enterprise"},
    "org7": {"id": "org7", "name": "Startup Inc", "plan": "free"},
}

_PERMISSIONS_DB = {
    ("u1", "org42"): ["admin", "billing", "deploy"],
    ("u2", "org7"): ["viewer"],
}

_AUDIT_LOG: list[dict] = []

_NOTIFICATIONS_SENT: list[dict] = []


async def _sim_delay():
    """Simulate network latency."""
    await asyncio.sleep(0.01)


# ---------------------------------------------------------------------------
# CALLBACK-BASED VERSION  (5 levels deep)
# ---------------------------------------------------------------------------

def fetch_user_cb(user_id: str, callback: Callable):
    async def _run():
        await _sim_delay()
        user = _USERS_DB.get(user_id)
        if user is None:
            callback(ValueError(f"User {user_id} not found"), None)
        else:
            callback(None, dict(user))
    asyncio.ensure_future(_run())


def fetch_org_cb(org_id: str, callback: Callable):
    async def _run():
        await _sim_delay()
        org = _ORGS_DB.get(org_id)
        if org is None:
            callback(ValueError(f"Org {org_id} not found"), None)
        else:
            callback(None, dict(org))
    asyncio.ensure_future(_run())


def fetch_permissions_cb(user_id: str, org_id: str, callback: Callable):
    async def _run():
        await _sim_delay()
        perms = _PERMISSIONS_DB.get((user_id, org_id))
        if perms is None:
            callback(ValueError("Permissions not found"), None)
        else:
            callback(None, list(perms))
    asyncio.ensure_future(_run())


def write_audit_log_cb(entry: dict, callback: Callable):
    async def _run():
        await _sim_delay()
        _AUDIT_LOG.append(entry)
        callback(None, True)
    asyncio.ensure_future(_run())


def send_notification_cb(notification: dict, callback: Callable):
    async def _run():
        await _sim_delay()
        _NOTIFICATIONS_SENT.append(notification)
        callback(None, True)
    asyncio.ensure_future(_run())


def process_user_callback_hell(user_id: str, final_callback: Callable):
    """
    5-level nested callback pyramid:
      1. fetch user
        2. fetch org
          3. fetch permissions
            4. write audit log
              5. send notification
    """
    def on_user(err, user):                                         # Level 1
        if err:
            final_callback(err, None)
            return
        def on_org(err, org):                                       # Level 2
            if err:
                final_callback(err, None)
                return
            def on_perms(err, perms):                               # Level 3
                if err:
                    final_callback(err, None)
                    return
                audit_entry = {
                    "action": "access_check",
                    "user": user["name"],
                    "org": org["name"],
                    "permissions": perms,
                }
                def on_audit(err, _ok):                             # Level 4
                    if err:
                        final_callback(err, None)
                        return
                    note = {
                        "to": user["name"],
                        "message": f"Access verified for {org['name']}",
                        "permissions": perms,
                    }
                    def on_notify(err, _ok):                        # Level 5
                        if err:
                            final_callback(err, None)
                            return
                        result = {
                            "user": user,
                            "org": org,
                            "permissions": perms,
                            "audit_logged": True,
                            "notified": True,
                        }
                        final_callback(None, result)
                    send_notification_cb(note, on_notify)
                write_audit_log_cb(audit_entry, on_audit)
            fetch_permissions_cb(user["id"], org["id"], on_perms)
        fetch_org_cb(user["org_id"], on_org)
    fetch_user_cb(user_id, on_user)


async def run_callback_version(user_id: str) -> dict:
    """Bridge: run the callback version inside an async context."""
    future: asyncio.Future = asyncio.get_event_loop().create_future()

    def done(err, result):
        if err:
            future.set_exception(err)
        else:
            future.set_result(result)

    process_user_callback_hell(user_id, done)
    return await future


# ---------------------------------------------------------------------------
# ASYNC/AWAIT VERSION  (flat, readable, same behavior)
# ---------------------------------------------------------------------------

async def fetch_user(user_id: str) -> dict:
    await _sim_delay()
    user = _USERS_DB.get(user_id)
    if user is None:
        raise ValueError(f"User {user_id} not found")
    return dict(user)


async def fetch_org(org_id: str) -> dict:
    await _sim_delay()
    org = _ORGS_DB.get(org_id)
    if org is None:
        raise ValueError(f"Org {org_id} not found")
    return dict(org)


async def fetch_permissions(user_id: str, org_id: str) -> list[str]:
    await _sim_delay()
    perms = _PERMISSIONS_DB.get((user_id, org_id))
    if perms is None:
        raise ValueError("Permissions not found")
    return list(perms)


async def write_audit_log(entry: dict) -> bool:
    await _sim_delay()
    _AUDIT_LOG.append(entry)
    return True


async def send_notification(notification: dict) -> bool:
    await _sim_delay()
    _NOTIFICATIONS_SENT.append(notification)
    return True


async def process_user_async(user_id: str) -> dict:
    """
    Same 5-step pipeline, flat async/await — no nesting.
    Errors propagate naturally via exceptions.
    """
    user = await fetch_user(user_id)
    org = await fetch_org(user["org_id"])
    permissions = await fetch_permissions(user["id"], org["id"])

    audit_entry = {
        "action": "access_check",
        "user": user["name"],
        "org": org["name"],
        "permissions": permissions,
    }
    await write_audit_log(audit_entry)

    notification = {
        "to": user["name"],
        "message": f"Access verified for {org['name']}",
        "permissions": permissions,
    }
    await send_notification(notification)

    return {
        "user": user,
        "org": org,
        "permissions": permissions,
        "audit_logged": True,
        "notified": True,
    }


# ---------------------------------------------------------------------------
# ERROR HANDLING DEMONSTRATION
# ---------------------------------------------------------------------------

async def process_user_safe(user_id: str) -> dict:
    """
    Production-style wrapper with granular error handling.
    """
    try:
        user = await fetch_user(user_id)
    except ValueError:
        return {"error": "user_not_found", "user_id": user_id}

    try:
        org = await fetch_org(user["org_id"])
    except ValueError:
        return {"error": "org_not_found", "org_id": user["org_id"]}

    try:
        permissions = await fetch_permissions(user["id"], org["id"])
    except ValueError:
        return {"error": "permissions_not_found", "user_id": user_id, "org_id": org["id"]}

    try:
        audit_entry = {
            "action": "access_check",
            "user": user["name"],
            "org": org["name"],
            "permissions": permissions,
        }
        await write_audit_log(audit_entry)
    except Exception as exc:
        return {"error": "audit_failed", "detail": str(exc)}

    try:
        notification = {
            "to": user["name"],
            "message": f"Access verified for {org['name']}",
            "permissions": permissions,
        }
        await send_notification(notification)
    except Exception as exc:
        return {"error": "notification_failed", "detail": str(exc)}

    return {
        "user": user,
        "org": org,
        "permissions": permissions,
        "audit_logged": True,
        "notified": True,
    }


# ---------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------

async def test_behavior_preserved():
    """Both versions must return identical results for the same inputs."""

    # --- Happy path: user u1 (enterprise admin) ---
    _AUDIT_LOG.clear()
    _NOTIFICATIONS_SENT.clear()
    cb_result = await run_callback_version("u1")

    audit_from_cb = list(_AUDIT_LOG)
    notif_from_cb = list(_NOTIFICATIONS_SENT)

    _AUDIT_LOG.clear()
    _NOTIFICATIONS_SENT.clear()
    async_result = await process_user_async("u1")

    audit_from_async = list(_AUDIT_LOG)
    notif_from_async = list(_NOTIFICATIONS_SENT)

    assert cb_result == async_result, f"Result mismatch:\n  CB:    {cb_result}\n  ASYNC: {async_result}"
    assert audit_from_cb == audit_from_async, "Audit log mismatch"
    assert notif_from_cb == notif_from_async, "Notification mismatch"

    assert async_result["user"]["name"] == "Alice"
    assert async_result["org"]["name"] == "Acme Corp"
    assert async_result["permissions"] == ["admin", "billing", "deploy"]
    assert async_result["audit_logged"] is True
    assert async_result["notified"] is True

    # --- Happy path: user u2 (free viewer) ---
    _AUDIT_LOG.clear()
    _NOTIFICATIONS_SENT.clear()
    cb_result2 = await run_callback_version("u2")

    _AUDIT_LOG.clear()
    _NOTIFICATIONS_SENT.clear()
    async_result2 = await process_user_async("u2")

    assert cb_result2 == async_result2, "u2 result mismatch"
    assert async_result2["user"]["name"] == "Bob"
    assert async_result2["org"]["plan"] == "free"
    assert async_result2["permissions"] == ["viewer"]


async def test_error_handling():
    """Error paths: callback version raises, async version raises or returns error dict."""

    # Callback version: unknown user raises ValueError
    try:
        await run_callback_version("unknown")
        assert False, "Should have raised"
    except ValueError as e:
        assert "not found" in str(e)

    # Async version: unknown user raises ValueError
    try:
        await process_user_async("unknown")
        assert False, "Should have raised"
    except ValueError as e:
        assert "not found" in str(e)

    # Safe version: unknown user returns error dict instead of raising
    safe_result = await process_user_safe("unknown")
    assert safe_result["error"] == "user_not_found"
    assert safe_result["user_id"] == "unknown"


async def test_audit_and_notification_side_effects():
    """Verify side effects are recorded correctly."""
    _AUDIT_LOG.clear()
    _NOTIFICATIONS_SENT.clear()

    await process_user_async("u1")
    await process_user_async("u2")

    assert len(_AUDIT_LOG) == 2
    assert _AUDIT_LOG[0]["user"] == "Alice"
    assert _AUDIT_LOG[1]["user"] == "Bob"

    assert len(_NOTIFICATIONS_SENT) == 2
    assert _NOTIFICATIONS_SENT[0]["to"] == "Alice"
    assert _NOTIFICATIONS_SENT[1]["to"] == "Bob"


async def test_safe_version_all_happy():
    """Safe wrapper returns full result on success."""
    _AUDIT_LOG.clear()
    _NOTIFICATIONS_SENT.clear()

    result = await process_user_safe("u1")
    assert "error" not in result
    assert result["user"]["name"] == "Alice"
    assert result["audit_logged"] is True
    assert result["notified"] is True


async def main():
    await test_behavior_preserved()
    print("PASS  test_behavior_preserved")

    await test_error_handling()
    print("PASS  test_error_handling")

    await test_audit_and_notification_side_effects()
    print("PASS  test_audit_and_notification_side_effects")

    await test_safe_version_all_happy()
    print("PASS  test_safe_version_all_happy")

    print("\nAll assertions passed. Callback and async/await versions behave identically.")


if __name__ == "__main__":
    asyncio.run(main())
