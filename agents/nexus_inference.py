#!/usr/bin/env python3
"""
nexus_inference.py — Nexus local inference engine
===================================================
All agent LLM calls go through this module.
Model selection, routing, and provider details are internal — never exposed.

Public API:
  - is_engine_up() -> bool
  - infer(prompt, num_ctx, hint) -> tuple[str, bool]
"""
import os
import json
import time

_API_BASE = os.environ.get("NEXUS_INFERENCE_API", "http://127.0.0.1:11434")
_CODE_MODEL = os.environ.get("NEXUS_CODE_MODEL", "qwen2.5-coder:7b")
_CHAT_MODEL = os.environ.get("NEXUS_CHAT_MODEL", "llama3.1:8b")
_LAST_CHECK = [0.0]
_ENGINE_UP  = [None]
_CHECK_TTL  = 30


def is_engine_up() -> bool:
    """Check Nexus inference engine reachability (cached 30s)."""
    now = time.time()
    if _ENGINE_UP[0] is not None and (now - _LAST_CHECK[0]) < _CHECK_TTL:
        return _ENGINE_UP[0]
    try:
        import urllib.request
        with urllib.request.urlopen(f"{_API_BASE}/api/tags", timeout=3) as r:
            _ENGINE_UP[0] = r.status == 200
    except Exception:
        _ENGINE_UP[0] = False
    _LAST_CHECK[0] = now
    return _ENGINE_UP[0]


def _raw_infer(prompt: str, model: str, num_ctx: int = 8192) -> str:
    """Internal inference call. Raises on failure."""
    import urllib.request
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": num_ctx, "temperature": 0.1},
    }).encode()
    req = urllib.request.Request(
        f"{_API_BASE}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read()).get("response", "")


def infer(prompt: str, num_ctx: int = 8192,
          hint: str = "", mode: str = "code") -> tuple[str, bool]:
    """
    Run inference via Nexus engine.
    Returns (response_text, success_bool).
    If engine offline: returns graceful fallback and False.

    mode: 'code' for code generation, 'chat' for conversational tasks.
    """
    if not is_engine_up():
        fallback = (
            f"[NEXUS_OFFLINE] Nexus inference engine unavailable.\n"
            f"Context: {hint[:200]}\n"
            f"Task queued for re-execution when engine restarts."
        )
        return fallback, False
    model = _CODE_MODEL if mode == "code" else _CHAT_MODEL
    try:
        return _raw_infer(prompt, model, num_ctx), True
    except Exception as e:
        return f"[NEXUS_ERROR] {e}", False


def chat(messages: list, system: str = "") -> str:
    """
    Multi-turn chat via Nexus engine.
    messages: list of {"role": str, "content": str}
    Returns assistant reply string.
    """
    if not is_engine_up():
        return "Nexus inference engine is currently offline. Please try again shortly."
    import urllib.request
    payload = json.dumps({
        "model": _CHAT_MODEL,
        "messages": ([{"role": "system", "content": system}] if system else []) + messages,
        "stream": False,
        "options": {"num_ctx": 8192, "temperature": 0.2},
    }).encode()
    req = urllib.request.Request(
        f"{_API_BASE}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read()).get("message", {}).get("content", "")
    except Exception as e:
        return f"Nexus engine error: {e}"
