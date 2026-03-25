"""
Feature Flag System — enable/disable features per user/environment.
Store in JSON file. Decorator @feature_required('flag_name').
Percentage rollout support. REST API to toggle flags.
"""

import json
import os
import hashlib
import functools
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Any, Dict, List, Optional


class FeatureFlags:
    """Core feature flag engine backed by a JSON file."""

    def __init__(self, storage_path: str = "feature_flags.json"):
        self._path = storage_path
        self._lock = threading.Lock()
        # Initialize with empty dict if file missing or empty
        needs_init = not os.path.exists(self._path)
        if not needs_init:
            needs_init = os.path.getsize(self._path) == 0
        if needs_init:
            self._save({})

    # ── persistence ──────────────────────────────────────────────

    def _load(self) -> dict:
        with open(self._path, "r") as f:
            return json.load(f)

    def _save(self, data: dict) -> None:
        with open(self._path, "w") as f:
            json.dump(data, f, indent=2)

    # ── flag CRUD ────────────────────────────────────────────────

    def create_flag(
        self,
        name: str,
        enabled: bool = False,
        environments: Optional[List[str]] = None,
        users: Optional[List[str]] = None,
        percentage: int = 100,
        description: str = "",
    ) -> dict:
        with self._lock:
            data = self._load()
            data[name] = {
                "enabled": enabled,
                "environments": environments or [],
                "users": users or [],
                "percentage": max(0, min(100, percentage)),
                "description": description,
            }
            self._save(data)
            return data[name]

    def get_flag(self, name: str) -> Optional[dict]:
        return self._load().get(name)

    def list_flags(self) -> dict:
        return self._load()

    def delete_flag(self, name: str) -> bool:
        with self._lock:
            data = self._load()
            if name not in data:
                return False
            del data[name]
            self._save(data)
            return True

    def toggle_flag(self, name: str, enabled: bool) -> Optional[dict]:
        with self._lock:
            data = self._load()
            if name not in data:
                return None
            data[name]["enabled"] = enabled
            self._save(data)
            return data[name]

    def update_flag(self, name: str, updates: dict) -> Optional[dict]:
        with self._lock:
            data = self._load()
            if name not in data:
                return None
            for key in ("enabled", "environments", "users", "percentage", "description"):
                if key in updates:
                    val = updates[key]
                    if key == "percentage":
                        val = max(0, min(100, int(val)))
                    data[name][key] = val
            self._save(data)
            return data[name]

    # ── evaluation ───────────────────────────────────────────────

    def is_enabled(
        self,
        name: str,
        user: Optional[str] = None,
        environment: Optional[str] = None,
    ) -> bool:
        flag = self.get_flag(name)
        if flag is None or not flag["enabled"]:
            return False

        # environment gate
        if flag["environments"] and environment not in flag["environments"]:
            return False

        # explicit user allowlist — if set, only listed users pass
        if flag["users"]:
            if user and user in flag["users"]:
                return True
            return False

        # percentage rollout (deterministic per user+flag)
        if flag["percentage"] < 100:
            if user is None:
                return False
            bucket = int(hashlib.md5(f"{name}:{user}".encode()).hexdigest(), 16) % 100
            return bucket < flag["percentage"]

        return True


# ── singleton for decorator use ──────────────────────────────────

_default_instance: Optional[FeatureFlags] = None


def get_default(path: str = "feature_flags.json") -> FeatureFlags:
    global _default_instance
    if _default_instance is None:
        _default_instance = FeatureFlags(path)
    return _default_instance


def set_default(instance: FeatureFlags) -> None:
    global _default_instance
    _default_instance = instance


# ── decorator ────────────────────────────────────────────────────


def feature_required(
    flag_name: str,
    user_kwarg: str = "user",
    env_kwarg: str = "environment",
    fallback: Any = None,
):
    """Decorator that gates a function behind a feature flag.

    If the flag is disabled for the given user/environment the *fallback*
    value is returned instead of calling the wrapped function.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            ff = get_default()
            user = kwargs.get(user_kwarg)
            env = kwargs.get(env_kwarg)
            if not ff.is_enabled(flag_name, user=user, environment=env):
                return fallback
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# ── REST API ─────────────────────────────────────────────────────


class FlagAPIHandler(BaseHTTPRequestHandler):
    """Minimal REST API to manage feature flags.

    Routes:
        GET  /flags              — list all flags
        GET  /flags/<name>       — get one flag
        GET  /flags/<name>/check?user=&env= — evaluate flag
        POST /flags              — create flag  (JSON body)
        PUT  /flags/<name>       — update flag  (JSON body)
        DELETE /flags/<name>     — delete flag
    """

    ff: FeatureFlags  # set on class before serving

    def _send_json(self, status: int, body: Any) -> None:
        payload = json.dumps(body, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        return json.loads(raw) if raw else {}

    def _parse_path(self):
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        qs = parse_qs(parsed.query)
        return parts, qs

    # GET
    def do_GET(self):
        parts, qs = self._parse_path()
        if parts == ["flags"]:
            self._send_json(200, self.ff.list_flags())
        elif len(parts) == 2 and parts[0] == "flags":
            flag = self.ff.get_flag(parts[1])
            if flag is None:
                self._send_json(404, {"error": "not_found"})
            else:
                self._send_json(200, flag)
        elif len(parts) == 3 and parts[0] == "flags" and parts[2] == "check":
            user = qs.get("user", [None])[0]
            env = qs.get("env", [None])[0]
            result = self.ff.is_enabled(parts[1], user=user, environment=env)
            self._send_json(200, {"flag": parts[1], "enabled": result})
        else:
            self._send_json(404, {"error": "not_found"})

    # POST
    def do_POST(self):
        parts, _ = self._parse_path()
        if parts == ["flags"]:
            body = self._read_body()
            name = body.pop("name", None)
            if not name:
                self._send_json(400, {"error": "name is required"})
                return
            flag = self.ff.create_flag(name, **body)
            self._send_json(201, flag)
        else:
            self._send_json(404, {"error": "not_found"})

    # PUT
    def do_PUT(self):
        parts, _ = self._parse_path()
        if len(parts) == 2 and parts[0] == "flags":
            body = self._read_body()
            flag = self.ff.update_flag(parts[1], body)
            if flag is None:
                self._send_json(404, {"error": "not_found"})
            else:
                self._send_json(200, flag)
        else:
            self._send_json(404, {"error": "not_found"})

    # DELETE
    def do_DELETE(self):
        parts, _ = self._parse_path()
        if len(parts) == 2 and parts[0] == "flags":
            ok = self.ff.delete_flag(parts[1])
            if not ok:
                self._send_json(404, {"error": "not_found"})
            else:
                self._send_json(200, {"deleted": parts[1]})
        else:
            self._send_json(404, {"error": "not_found"})

    def log_message(self, format, *args):
        pass  # silence logs during tests


def run_api(ff: FeatureFlags, host: str = "127.0.0.1", port: int = 8080):
    """Start the REST API server (blocking)."""
    FlagAPIHandler.ff = ff
    server = HTTPServer((host, port), FlagAPIHandler)
    print(f"Feature flag API running on http://{host}:{port}")
    server.serve_forever()


# ── main: assertions ─────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile
    import urllib.request

    # ---------- core engine tests ----------

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        path = tmp.name

    try:
        ff = FeatureFlags(path)

        # create & get
        ff.create_flag("dark_mode", enabled=True, description="Dark theme")
        flag = ff.get_flag("dark_mode")
        assert flag is not None
        assert flag["enabled"] is True
        assert flag["description"] == "Dark theme"
        assert flag["percentage"] == 100
        print("[PASS] create & get")

        # toggle
        ff.toggle_flag("dark_mode", False)
        assert ff.is_enabled("dark_mode") is False
        ff.toggle_flag("dark_mode", True)
        assert ff.is_enabled("dark_mode") is True
        print("[PASS] toggle")

        # environment gating
        ff.create_flag("beta_ui", enabled=True, environments=["staging", "dev"])
        assert ff.is_enabled("beta_ui", environment="staging") is True
        assert ff.is_enabled("beta_ui", environment="production") is False
        assert ff.is_enabled("beta_ui") is False  # no env specified, env list non-empty
        print("[PASS] environment gating")

        # user allowlist
        ff.create_flag("vip_feature", enabled=True, users=["alice", "bob"])
        assert ff.is_enabled("vip_feature", user="alice") is True
        assert ff.is_enabled("vip_feature", user="charlie") is False
        assert ff.is_enabled("vip_feature") is False  # no user
        print("[PASS] user allowlist")

        # percentage rollout (deterministic)
        ff.create_flag("new_algo", enabled=True, percentage=50)
        results = {ff.is_enabled("new_algo", user=f"user_{i}") for i in range(200)}
        assert True in results and False in results, "50% rollout should include both"
        # same user always gets same result
        r1 = ff.is_enabled("new_algo", user="stable_user")
        r2 = ff.is_enabled("new_algo", user="stable_user")
        assert r1 == r2
        print("[PASS] percentage rollout (deterministic)")

        # 0% rollout — nobody gets it
        ff.create_flag("zero_pct", enabled=True, percentage=0)
        assert all(
            not ff.is_enabled("zero_pct", user=f"u{i}") for i in range(100)
        )
        print("[PASS] 0% rollout")

        # 100% rollout — everyone gets it
        ff.create_flag("full_pct", enabled=True, percentage=100)
        assert all(
            ff.is_enabled("full_pct", user=f"u{i}") for i in range(100)
        )
        print("[PASS] 100% rollout")

        # percentage clamping
        ff.create_flag("clamped", enabled=True, percentage=150)
        assert ff.get_flag("clamped")["percentage"] == 100
        ff.create_flag("clamped_neg", enabled=True, percentage=-10)
        assert ff.get_flag("clamped_neg")["percentage"] == 0
        print("[PASS] percentage clamping")

        # update
        ff.update_flag("dark_mode", {"percentage": 75, "description": "updated"})
        flag = ff.get_flag("dark_mode")
        assert flag["percentage"] == 75
        assert flag["description"] == "updated"
        print("[PASS] update")

        # list
        all_flags = ff.list_flags()
        assert "dark_mode" in all_flags
        assert "beta_ui" in all_flags
        print("[PASS] list flags")

        # delete
        assert ff.delete_flag("dark_mode") is True
        assert ff.get_flag("dark_mode") is None
        assert ff.delete_flag("nonexistent") is False
        print("[PASS] delete")

        # disabled flag always returns False
        ff.create_flag("off_flag", enabled=False, users=["alice"])
        assert ff.is_enabled("off_flag", user="alice") is False
        print("[PASS] disabled flag")

        # ---------- decorator tests ----------

        set_default(ff)
        ff.create_flag("new_dashboard", enabled=True, environments=["prod"])

        @feature_required("new_dashboard", fallback="old_dashboard")
        def get_dashboard(user=None, environment=None):
            return "new_dashboard"

        assert get_dashboard(environment="prod") == "new_dashboard"
        assert get_dashboard(environment="staging") == "old_dashboard"
        print("[PASS] @feature_required decorator")

        ff.create_flag("experimental", enabled=True, users=["dev1"])

        @feature_required("experimental")
        def experimental_fn(user=None):
            return 42

        assert experimental_fn(user="dev1") == 42
        assert experimental_fn(user="other") is None  # fallback=None
        print("[PASS] decorator with user gate")

        # ---------- REST API tests ----------

        FlagAPIHandler.ff = ff
        server = HTTPServer(("127.0.0.1", 0), FlagAPIHandler)
        port = server.server_address[1]
        base = f"http://127.0.0.1:{port}"
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()

        def api(method, path, body=None):
            data = json.dumps(body).encode() if body else None
            req = urllib.request.Request(
                f"{base}{path}", data=data, method=method,
                headers={"Content-Type": "application/json"} if data else {},
            )
            try:
                with urllib.request.urlopen(req) as resp:
                    return resp.status, json.loads(resp.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())

        # POST /flags — create
        status, body = api("POST", "/flags", {
            "name": "api_flag", "enabled": True, "percentage": 60,
        })
        assert status == 201
        assert body["enabled"] is True
        assert body["percentage"] == 60
        print("[PASS] API POST /flags")

        # GET /flags — list
        status, body = api("GET", "/flags")
        assert status == 200
        assert "api_flag" in body
        print("[PASS] API GET /flags")

        # GET /flags/<name>
        status, body = api("GET", "/flags/api_flag")
        assert status == 200
        assert body["percentage"] == 60
        print("[PASS] API GET /flags/<name>")

        # GET /flags/<name>/check
        status, body = api("GET", "/flags/api_flag/check?user=test_user")
        assert status == 200
        assert "enabled" in body
        print("[PASS] API GET /flags/<name>/check")

        # PUT /flags/<name> — update / toggle
        status, body = api("PUT", "/flags/api_flag", {"enabled": False})
        assert status == 200
        assert body["enabled"] is False
        print("[PASS] API PUT /flags/<name>")

        # DELETE /flags/<name>
        status, body = api("DELETE", "/flags/api_flag")
        assert status == 200
        assert body["deleted"] == "api_flag"
        status, body = api("GET", "/flags/api_flag")
        assert status == 404
        print("[PASS] API DELETE /flags/<name>")

        # 404 for unknown flag
        status, _ = api("GET", "/flags/nope")
        assert status == 404
        print("[PASS] API 404 handling")

        server.shutdown()
        print("\n=== All assertions passed ===")

    finally:
        os.unlink(path)
