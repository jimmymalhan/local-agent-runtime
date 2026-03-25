"""
ConfigManager: Load configuration from YAML/JSON/env vars with priority: env > file > defaults.
Supports nested keys, type coercion, hot-reload on file change, and validation.
"""

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type, Union

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


class ConfigValidationError(Exception):
    pass


class ConfigManager:
    def __init__(
        self,
        defaults: Optional[Dict[str, Any]] = None,
        file_path: Optional[str] = None,
        env_prefix: str = "",
        env_separator: str = "__",
        validators: Optional[Dict[str, Callable[[Any], bool]]] = None,
        type_schema: Optional[Dict[str, Type]] = None,
    ):
        self._defaults: Dict[str, Any] = defaults or {}
        self._file_path: Optional[Path] = Path(file_path) if file_path else None
        self._env_prefix: str = env_prefix
        self._env_separator: str = env_separator
        self._validators: Dict[str, Callable[[Any], bool]] = validators or {}
        self._type_schema: Dict[str, Type] = type_schema or {}
        self._file_config: Dict[str, Any] = {}
        self._listeners: List[Callable[[Dict[str, Any]], None]] = []
        self._lock = threading.RLock()
        self._watch_thread: Optional[threading.Thread] = None
        self._watching = False
        self._last_mtime: float = 0.0

        if self._file_path and self._file_path.exists():
            self._file_config = self._load_file(self._file_path)
            self._last_mtime = self._file_path.stat().st_mtime

    # ── File loading ──────────────────────────────────────────────

    @staticmethod
    def _load_file(path: Path) -> Dict[str, Any]:
        text = path.read_text(encoding="utf-8")
        suffix = path.suffix.lower()
        if suffix in (".yaml", ".yml"):
            if not HAS_YAML:
                raise ImportError("PyYAML is required to load YAML files: pip install pyyaml")
            data = yaml.safe_load(text)
        elif suffix == ".json":
            data = json.loads(text)
        else:
            raise ValueError(f"Unsupported config file format: {suffix}")
        return data if isinstance(data, dict) else {}

    # ── Nested key helpers ────────────────────────────────────────

    @staticmethod
    def _get_nested(d: Dict[str, Any], keys: List[str]) -> Any:
        current = d
        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                raise KeyError(".".join(keys))
        return current

    @staticmethod
    def _set_nested(d: Dict[str, Any], keys: List[str], value: Any) -> None:
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value

    @staticmethod
    def _has_nested(d: Dict[str, Any], keys: List[str]) -> bool:
        current = d
        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return False
        return True

    # ── Environment variable overlay ──────────────────────────────

    def _env_key(self, dotted_key: str) -> str:
        return (self._env_prefix + dotted_key.replace(".", self._env_separator)).upper()

    def _get_env(self, dotted_key: str) -> Optional[str]:
        return os.environ.get(self._env_key(dotted_key))

    def _collect_env_overrides(self) -> Dict[str, str]:
        prefix = self._env_prefix.upper()
        overrides: Dict[str, str] = {}
        for key, value in os.environ.items():
            if prefix and key.startswith(prefix):
                stripped = key[len(prefix):]
                dotted = stripped.lower().replace(self._env_separator.upper(), ".").replace(self._env_separator, ".")
                overrides[dotted] = value
            elif not prefix:
                pass  # without a prefix we only match explicit keys
        return overrides

    # ── Type coercion ─────────────────────────────────────────────

    def _coerce(self, dotted_key: str, value: Any) -> Any:
        target_type = self._type_schema.get(dotted_key)
        if target_type is None:
            # Infer from defaults
            keys = dotted_key.split(".")
            if self._has_nested(self._defaults, keys):
                default_val = self._get_nested(self._defaults, keys)
                if default_val is not None:
                    target_type = type(default_val)
        if target_type is None or isinstance(value, target_type):
            return value
        return self._cast(value, target_type)

    @staticmethod
    def _cast(value: Any, target: Type) -> Any:
        if target is bool:
            if isinstance(value, str):
                if value.lower() in ("true", "1", "yes", "on"):
                    return True
                if value.lower() in ("false", "0", "no", "off"):
                    return False
            return bool(value)
        if target is int:
            return int(value)
        if target is float:
            return float(value)
        if target is str:
            return str(value)
        if target is list and isinstance(value, str):
            return [v.strip() for v in value.split(",")]
        return target(value)

    # ── Validation ────────────────────────────────────────────────

    def _validate(self, dotted_key: str, value: Any) -> None:
        validator = self._validators.get(dotted_key)
        if validator is not None:
            if not validator(value):
                raise ConfigValidationError(
                    f"Validation failed for '{dotted_key}' with value {value!r}"
                )

    # ── Public API ────────────────────────────────────────────────

    def get(self, dotted_key: str, default: Any = None) -> Any:
        with self._lock:
            keys = dotted_key.split(".")

            # Priority 1: environment variable
            env_val = self._get_env(dotted_key)
            if env_val is not None:
                coerced = self._coerce(dotted_key, env_val)
                self._validate(dotted_key, coerced)
                return coerced

            # Priority 2: file config
            if self._has_nested(self._file_config, keys):
                val = self._get_nested(self._file_config, keys)
                coerced = self._coerce(dotted_key, val)
                self._validate(dotted_key, coerced)
                return coerced

            # Priority 3: defaults
            if self._has_nested(self._defaults, keys):
                val = self._get_nested(self._defaults, keys)
                self._validate(dotted_key, val)
                return val

            return default

    def set(self, dotted_key: str, value: Any) -> None:
        with self._lock:
            coerced = self._coerce(dotted_key, value)
            self._validate(dotted_key, coerced)
            keys = dotted_key.split(".")
            self._set_nested(self._file_config, keys, coerced)

    def all(self) -> Dict[str, Any]:
        with self._lock:
            merged = self._deep_merge(self._defaults, self._file_config)
            env_overrides = self._collect_env_overrides()
            for dotted, raw in env_overrides.items():
                keys = dotted.split(".")
                coerced = self._coerce(dotted, raw)
                self._set_nested(merged, keys, coerced)
            return merged

    def reload(self) -> None:
        if self._file_path and self._file_path.exists():
            with self._lock:
                self._file_config = self._load_file(self._file_path)
                self._last_mtime = self._file_path.stat().st_mtime
            self._notify_listeners()

    def on_change(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._listeners.append(callback)

    def _notify_listeners(self) -> None:
        current = self.all()
        for cb in self._listeners:
            try:
                cb(current)
            except Exception:
                pass

    # ── Hot-reload watcher ────────────────────────────────────────

    def watch(self, interval: float = 1.0) -> None:
        if self._watching or self._file_path is None:
            return
        self._watching = True
        self._watch_thread = threading.Thread(
            target=self._watch_loop, args=(interval,), daemon=True
        )
        self._watch_thread.start()

    def stop_watching(self) -> None:
        self._watching = False
        if self._watch_thread:
            self._watch_thread.join(timeout=5)
            self._watch_thread = None

    def _watch_loop(self, interval: float) -> None:
        while self._watching:
            time.sleep(interval)
            if self._file_path and self._file_path.exists():
                mtime = self._file_path.stat().st_mtime
                if mtime > self._last_mtime:
                    self.reload()

    # ── Deep merge ────────────────────────────────────────────────

    @staticmethod
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        result = {}
        for key in set(list(base.keys()) + list(override.keys())):
            if key in override and key in base:
                if isinstance(base[key], dict) and isinstance(override[key], dict):
                    result[key] = ConfigManager._deep_merge(base[key], override[key])
                else:
                    result[key] = override[key]
            elif key in override:
                result[key] = override[key]
            else:
                result[key] = base[key]
        return result


# ── Main: assertions ──────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile

    # ── Test 1: Defaults ──────────────────────────────────────────
    cm = ConfigManager(defaults={"server": {"host": "localhost", "port": 8080}, "debug": False})
    assert cm.get("server.host") == "localhost"
    assert cm.get("server.port") == 8080
    assert cm.get("debug") is False
    assert cm.get("missing", "fallback") == "fallback"
    print("PASS: defaults")

    # ── Test 2: JSON file overrides defaults ──────────────────────
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"server": {"port": 9090}, "feature_flag": True}, f)
        json_path = f.name

    cm = ConfigManager(
        defaults={"server": {"host": "localhost", "port": 8080}, "debug": False},
        file_path=json_path,
    )
    assert cm.get("server.host") == "localhost"  # from defaults
    assert cm.get("server.port") == 9090          # overridden by file
    assert cm.get("feature_flag") is True          # only in file
    assert cm.get("debug") is False                # only in defaults
    print("PASS: JSON file override")

    # ── Test 3: Env vars override file and defaults ───────────────
    os.environ["MYAPP__SERVER__PORT"] = "7070"
    os.environ["MYAPP__DEBUG"] = "true"
    cm = ConfigManager(
        defaults={"server": {"host": "localhost", "port": 8080}, "debug": False},
        file_path=json_path,
        env_prefix="MYAPP__",
        env_separator="__",
    )
    assert cm.get("server.port") == 7070   # env wins over file (9090) and default (8080)
    assert cm.get("debug") is True          # env wins over default (False)
    assert cm.get("server.host") == "localhost"  # no env override, falls to default
    del os.environ["MYAPP__SERVER__PORT"]
    del os.environ["MYAPP__DEBUG"]
    print("PASS: env var override")

    # ── Test 4: Type coercion ─────────────────────────────────────
    os.environ["T__COUNT"] = "42"
    os.environ["T__RATE"] = "3.14"
    os.environ["T__ENABLED"] = "yes"
    os.environ["T__TAGS"] = "a, b, c"
    cm = ConfigManager(
        defaults={"count": 0, "rate": 0.0, "enabled": False, "tags": []},
        env_prefix="T__",
        env_separator="__",
        type_schema={"tags": list},
    )
    assert cm.get("count") == 42
    assert abs(cm.get("rate") - 3.14) < 0.001
    assert cm.get("enabled") is True
    assert cm.get("tags") == ["a", "b", "c"]
    del os.environ["T__COUNT"]
    del os.environ["T__RATE"]
    del os.environ["T__ENABLED"]
    del os.environ["T__TAGS"]
    print("PASS: type coercion")

    # ── Test 5: Validation ────────────────────────────────────────
    cm = ConfigManager(
        defaults={"server": {"port": 8080}},
        validators={"server.port": lambda v: isinstance(v, int) and 1 <= v <= 65535},
    )
    assert cm.get("server.port") == 8080

    try:
        cm.set("server.port", 99999)
        assert False, "Should have raised ConfigValidationError"
    except ConfigValidationError:
        pass
    print("PASS: validation")

    # ── Test 6: set() and nested keys ─────────────────────────────
    cm = ConfigManager(defaults={"a": {"b": {"c": 1}}})
    assert cm.get("a.b.c") == 1
    cm.set("a.b.c", 2)
    assert cm.get("a.b.c") == 2
    cm.set("a.b.d", "new")
    assert cm.get("a.b.d") == "new"
    print("PASS: set and nested keys")

    # ── Test 7: Hot-reload ────────────────────────────────────────
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"value": 1}, f)
        reload_path = f.name

    reload_events: list = []
    cm = ConfigManager(file_path=reload_path)
    cm.on_change(lambda cfg: reload_events.append(cfg))
    assert cm.get("value") == 1

    cm.watch(interval=0.2)
    time.sleep(0.3)

    # Modify file
    with open(reload_path, "w") as f:
        json.dump({"value": 2}, f)

    time.sleep(0.5)
    cm.stop_watching()

    assert cm.get("value") == 2
    assert len(reload_events) >= 1
    assert reload_events[-1]["value"] == 2
    print("PASS: hot-reload")

    # ── Test 8: all() merges correctly ────────────────────────────
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"server": {"port": 3000}, "extra": "yes"}, f)
        all_path = f.name

    cm = ConfigManager(
        defaults={"server": {"host": "0.0.0.0", "port": 8080}, "debug": False},
        file_path=all_path,
    )
    merged = cm.all()
    assert merged["server"]["host"] == "0.0.0.0"
    assert merged["server"]["port"] == 3000
    assert merged["debug"] is False
    assert merged["extra"] == "yes"
    print("PASS: all() merge")

    # ── Test 9: YAML file ─────────────────────────────────────────
    if HAS_YAML:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump({"database": {"host": "db.local", "port": 5432}}, f)
            yaml_path = f.name

        cm = ConfigManager(
            defaults={"database": {"host": "localhost", "port": 5432, "name": "mydb"}},
            file_path=yaml_path,
        )
        assert cm.get("database.host") == "db.local"
        assert cm.get("database.port") == 5432
        assert cm.get("database.name") == "mydb"
        print("PASS: YAML file")
    else:
        print("SKIP: YAML (pyyaml not installed)")

    # ── Test 10: Deep merge edge cases ────────────────────────────
    base = {"a": {"x": 1, "y": 2}, "b": 10}
    over = {"a": {"y": 99, "z": 3}, "c": 20}
    result = ConfigManager._deep_merge(base, over)
    assert result == {"a": {"x": 1, "y": 99, "z": 3}, "b": 10, "c": 20}
    print("PASS: deep merge")

    # Cleanup temp files
    for p in [json_path, reload_path, all_path]:
        os.unlink(p)
    if HAS_YAML:
        os.unlink(yaml_path)

    print("\nAll assertions passed.")
