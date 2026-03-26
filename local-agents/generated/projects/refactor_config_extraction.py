"""
Refactor: Extract configuration from hardcoded class into dataclass Config
with support for environment variables, YAML files, and defaults.
Priority: env > yaml > defaults.
"""

from __future__ import annotations

import os
import tempfile
import textwrap
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, Optional, Type, TypeVar, get_type_hints

import yaml

T = TypeVar("T")


# ---------------------------------------------------------------------------
# 1. BEFORE: class with 15 hardcoded configuration values
# ---------------------------------------------------------------------------

class HardcodedService:
    """Original service with configuration buried in code."""

    def __init__(self):
        self.host = "localhost"
        self.port = 8080
        self.debug = False
        self.log_level = "INFO"
        self.max_connections = 100
        self.timeout_seconds = 30
        self.retry_count = 3
        self.retry_delay = 1.5
        self.db_host = "localhost"
        self.db_port = 5432
        self.db_name = "appdb"
        self.db_pool_size = 10
        self.cache_enabled = True
        self.cache_ttl = 300
        self.secret_key = "change-me"


# ---------------------------------------------------------------------------
# 2. AFTER: dataclass Config + YAML + env var loader
# ---------------------------------------------------------------------------

def _coerce(value: str, target_type: Type[T]) -> T:
    """Coerce a string value (from env or YAML) into the target Python type."""
    if target_type is bool:
        return value if isinstance(value, bool) else value.lower() in ("1", "true", "yes", "on")
    if target_type is int:
        return int(value)
    if target_type is float:
        return float(value)
    return value


@dataclass
class Config:
    """Application configuration with typed defaults.

    Resolution order (highest priority first):
        1. Environment variables  (prefix ``APP_``)
        2. YAML config file
        3. Dataclass defaults
    """

    host: str = "localhost"
    port: int = 8080
    debug: bool = False
    log_level: str = "INFO"
    max_connections: int = 100
    timeout_seconds: int = 30
    retry_count: int = 3
    retry_delay: float = 1.5
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "appdb"
    db_pool_size: int = 10
    cache_enabled: bool = True
    cache_ttl: int = 300
    secret_key: str = "change-me"

    ENV_PREFIX: str = field(default="APP_", init=False, repr=False)

    # ---- factory ----------------------------------------------------------

    @classmethod
    def load(
        cls,
        yaml_path: Optional[str | Path] = None,
        env_prefix: str = "APP_",
    ) -> "Config":
        """Build a Config by layering defaults < YAML < env vars."""
        yaml_values = cls._read_yaml(yaml_path) if yaml_path else {}
        env_values = cls._read_env(env_prefix)

        hints = get_type_hints(cls)
        init_fields = {f.name for f in fields(cls) if f.init}
        merged: Dict[str, Any] = {}

        for f in fields(cls):
            if f.name not in init_fields:
                continue
            target_type = hints[f.name]

            if f.name in env_values:
                merged[f.name] = _coerce(env_values[f.name], target_type)
            elif f.name in yaml_values:
                merged[f.name] = _coerce(yaml_values[f.name], target_type)
            # else: dataclass default is used automatically

        return cls(**merged)

    # ---- YAML loader ------------------------------------------------------

    @staticmethod
    def _read_yaml(path: str | Path) -> Dict[str, Any]:
        p = Path(path)
        if not p.exists():
            return {}
        with p.open("r") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else {}

    # ---- env loader -------------------------------------------------------

    @classmethod
    def _read_env(cls, prefix: str) -> Dict[str, str]:
        result: Dict[str, str] = {}
        init_field_names = {f.name for f in fields(cls) if f.init}
        for f in fields(cls):
            if f.name not in init_field_names:
                continue
            env_key = f"{prefix}{f.name.upper()}"
            val = os.environ.get(env_key)
            if val is not None:
                result[f.name] = val
        return result

    # ---- helpers ----------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.init}

    def to_yaml(self, path: str | Path) -> None:
        with Path(path).open("w") as fh:
            yaml.dump(self.to_dict(), fh, default_flow_style=False)


# ---------------------------------------------------------------------------
# 3. Refactored service — accepts Config instead of hardcoding values
# ---------------------------------------------------------------------------

class RefactoredService:
    """Service that receives its configuration externally."""

    def __init__(self, config: Config):
        self.config = config

    @property
    def db_url(self) -> str:
        return f"postgresql://{self.config.db_host}:{self.config.db_port}/{self.config.db_name}"

    def summary(self) -> Dict[str, Any]:
        return {
            "listen": f"{self.config.host}:{self.config.port}",
            "debug": self.config.debug,
            "log_level": self.config.log_level,
            "db": self.db_url,
            "pool": self.config.db_pool_size,
            "cache": self.config.cache_enabled,
            "cache_ttl": self.config.cache_ttl,
        }


# ---------------------------------------------------------------------------
# 4. Assertions & demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    # --- Test 1: pure defaults match the old hardcoded service -------------
    cfg_default = Config.load()
    old = HardcodedService()

    for f in fields(cfg_default):
        if not f.init:
            continue
        assert getattr(cfg_default, f.name) == getattr(old, f.name), (
            f"Default mismatch on {f.name}: "
            f"{getattr(cfg_default, f.name)!r} != {getattr(old, f.name)!r}"
        )
    print("[PASS] Test 1: defaults match original hardcoded values")

    # --- Test 2: YAML overrides defaults -----------------------------------
    yaml_content = textwrap.dedent("""\
        host: "0.0.0.0"
        port: 9090
        debug: true
        log_level: "DEBUG"
        max_connections: 200
        timeout_seconds: 60
        retry_count: 5
        retry_delay: 2.5
        db_host: "db.prod.internal"
        db_port: 5433
        db_name: "prod_db"
        db_pool_size: 25
        cache_enabled: false
        cache_ttl: 600
        secret_key: "yaml-secret-key-123"
    """)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as tmp:
        tmp.write(yaml_content)
        tmp_path = tmp.name

    try:
        cfg_yaml = Config.load(yaml_path=tmp_path)
        assert cfg_yaml.host == "0.0.0.0"
        assert cfg_yaml.port == 9090
        assert cfg_yaml.debug is True
        assert cfg_yaml.log_level == "DEBUG"
        assert cfg_yaml.max_connections == 200
        assert cfg_yaml.timeout_seconds == 60
        assert cfg_yaml.retry_count == 5
        assert cfg_yaml.retry_delay == 2.5
        assert cfg_yaml.db_host == "db.prod.internal"
        assert cfg_yaml.db_port == 5433
        assert cfg_yaml.db_name == "prod_db"
        assert cfg_yaml.db_pool_size == 25
        assert cfg_yaml.cache_enabled is False
        assert cfg_yaml.cache_ttl == 600
        assert cfg_yaml.secret_key == "yaml-secret-key-123"
        print("[PASS] Test 2: YAML overrides all 15 defaults")
    finally:
        os.unlink(tmp_path)

    # --- Test 3: env vars override YAML ------------------------------------
    yaml_partial = textwrap.dedent("""\
        host: "yaml-host"
        port: 7070
        debug: false
        secret_key: "yaml-secret"
    """)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as tmp:
        tmp.write(yaml_partial)
        tmp_path = tmp.name

    env_overrides = {
        "APP_HOST": "env-host",
        "APP_PORT": "3000",
        "APP_DEBUG": "true",
        "APP_SECRET_KEY": "env-secret-999",
    }

    original_env = {k: os.environ.get(k) for k in env_overrides}
    os.environ.update(env_overrides)

    try:
        cfg_env = Config.load(yaml_path=tmp_path)

        # env wins over YAML
        assert cfg_env.host == "env-host", f"got {cfg_env.host!r}"
        assert cfg_env.port == 3000, f"got {cfg_env.port!r}"
        assert cfg_env.debug is True, f"got {cfg_env.debug!r}"
        assert cfg_env.secret_key == "env-secret-999", f"got {cfg_env.secret_key!r}"

        # YAML value still used when env is absent
        # (none of the remaining fields had env overrides, so they fall to
        #  YAML or default)
        assert cfg_env.log_level == "INFO"  # default — not in YAML
        assert cfg_env.max_connections == 100  # default — not in YAML

        print("[PASS] Test 3: env vars override YAML; YAML overrides defaults")
    finally:
        for k, v in original_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        os.unlink(tmp_path)

    # --- Test 4: custom env prefix ----------------------------------------
    os.environ["MYAPP_HOST"] = "custom-prefix-host"
    os.environ["MYAPP_PORT"] = "4444"
    try:
        cfg_prefix = Config.load(env_prefix="MYAPP_")
        assert cfg_prefix.host == "custom-prefix-host"
        assert cfg_prefix.port == 4444
        assert cfg_prefix.db_name == "appdb"  # untouched default
        print("[PASS] Test 4: custom env prefix works")
    finally:
        os.environ.pop("MYAPP_HOST", None)
        os.environ.pop("MYAPP_PORT", None)

    # --- Test 5: round-trip to_dict / to_yaml ------------------------------
    cfg_rt = Config.load()
    d = cfg_rt.to_dict()
    assert len(d) == 15, f"Expected 15 config keys, got {len(d)}"
    assert d["host"] == "localhost"
    assert d["retry_delay"] == 1.5

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as tmp:
        tmp_path = tmp.name

    try:
        cfg_rt.to_yaml(tmp_path)
        cfg_reloaded = Config.load(yaml_path=tmp_path)
        assert cfg_reloaded.to_dict() == cfg_rt.to_dict()
        print("[PASS] Test 5: round-trip to_yaml -> load preserves all values")
    finally:
        os.unlink(tmp_path)

    # --- Test 6: RefactoredService uses Config correctly -------------------
    svc = RefactoredService(Config.load())
    assert svc.db_url == "postgresql://localhost:5432/appdb"
    summary = svc.summary()
    assert summary["listen"] == "localhost:8080"
    assert summary["debug"] is False
    assert summary["cache"] is True
    print("[PASS] Test 6: RefactoredService works with Config")

    # --- Test 7: missing YAML file is gracefully ignored -------------------
    cfg_missing = Config.load(yaml_path="/nonexistent/config.yaml")
    assert cfg_missing.host == "localhost"
    print("[PASS] Test 7: missing YAML file falls back to defaults")

    # --- Test 8: bool coercion edge cases ---------------------------------
    for truthy in ("1", "true", "True", "TRUE", "yes", "YES", "on", "ON"):
        assert _coerce(truthy, bool) is True, f"Expected True for {truthy!r}"
    for falsy in ("0", "false", "False", "no", "off", ""):
        assert _coerce(falsy, bool) is False, f"Expected False for {falsy!r}"
    print("[PASS] Test 8: bool coercion handles all common truthy/falsy strings")

    # --- Test 9: partial YAML (some keys only) ----------------------------
    yaml_sparse = textwrap.dedent("""\
        port: 1234
        db_name: "sparse_db"
    """)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as tmp:
        tmp.write(yaml_sparse)
        tmp_path = tmp.name
    try:
        cfg_sparse = Config.load(yaml_path=tmp_path)
        assert cfg_sparse.port == 1234
        assert cfg_sparse.db_name == "sparse_db"
        assert cfg_sparse.host == "localhost"  # default
        assert cfg_sparse.debug is False  # default
        print("[PASS] Test 9: partial YAML merges with defaults correctly")
    finally:
        os.unlink(tmp_path)

    print("\nAll 9 tests passed. Configuration extraction complete.")
