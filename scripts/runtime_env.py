#!/usr/bin/env python3
from __future__ import annotations
import json
import os
import pathlib
from typing import Optional, Dict


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME_ENV_PATH = REPO_ROOT / "state" / "runtime.env"
OPENCLAW_CONFIG_PATH = pathlib.Path.home() / ".openclaw" / "openclaw.json"


def parse_env_lines(text: str) -> Dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_runtime_env(path: Optional[pathlib.Path] = None, override: bool = False) -> Dict[str, str]:
    target = path or RUNTIME_ENV_PATH
    if not target.exists():
        return {}
    values = parse_env_lines(target.read_text())
    for key, value in values.items():
        if override or key not in os.environ:
            os.environ[key] = value
    return values


def read_runtime_env(path: Optional[pathlib.Path] = None) -> Dict[str, str]:
    target = path or RUNTIME_ENV_PATH
    if not target.exists():
        return {}
    return parse_env_lines(target.read_text())


def env_with_runtime(overrides: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    merged = dict(read_runtime_env())
    merged.update({key: str(value) for key, value in os.environ.items()})
    if overrides:
        merged.update({key: str(value) for key, value in overrides.items()})
    return merged


def write_runtime_env(values: Dict[str, str], path: Optional[pathlib.Path] = None) -> pathlib.Path:
    target = path or RUNTIME_ENV_PATH
    merged = read_runtime_env(target)
    for key, value in values.items():
        merged[key] = str(value)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f"{key}={merged[key]}\n" for key in sorted(merged))
    target.write_text(body)
    return target


def openclaw_config(path: pathlib.Path | None = None) -> dict:
    target = path or OPENCLAW_CONFIG_PATH
    if not target.exists():
        return {}
    try:
        body = json.loads(target.read_text())
    except json.JSONDecodeError:
        return {}
    return body if isinstance(body, dict) else {}


def openclaw_runtime_values(config: dict | None = None) -> dict[str, str]:
    body = config or openclaw_config()
    gateway = body.get("gateway", {})
    auth = gateway.get("auth", {})
    token = str(auth.get("token", "")).strip()
    port = int(gateway.get("port", 19000) or 19000)
    if not token:
        return {}
    return {
        "LOCAL_AGENT_ALLOW_REMOTE_FALLBACK": "1",
        "LOCAL_AGENT_ENABLE_OPENCLAW": "1",
        "LOCAL_AGENT_PROVIDER_PREFERENCE": "openclaw",
        "OPENCLAW_BASE_URL": f"http://127.0.0.1:{port}",
        "OPENCLAW_GATEWAY_TOKEN": token,
    }


def openclaw_status() -> dict[str, object]:
    config = openclaw_config()
    values = openclaw_runtime_values(config)
    token = values.get("OPENCLAW_GATEWAY_TOKEN", "")
    dashboard_url = ""
    if values.get("OPENCLAW_BASE_URL"):
        dashboard_url = values["OPENCLAW_BASE_URL"].rstrip("/") + "/"
        if token:
            dashboard_url += f"#token={token}"
    return {
        "configured": bool(values),
        "config_path": str(OPENCLAW_CONFIG_PATH),
        "base_url": values.get("OPENCLAW_BASE_URL", ""),
        "dashboard_url": dashboard_url,
        "provider_preference": values.get("LOCAL_AGENT_PROVIDER_PREFERENCE", ""),
        "remote_fallback": values.get("LOCAL_AGENT_ALLOW_REMOTE_FALLBACK") == "1",
        "token_present": bool(values.get("OPENCLAW_GATEWAY_TOKEN")),
    }
