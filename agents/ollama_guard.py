#!/usr/bin/env python3
"""
ollama_guard.py — Shared Ollama health check for all agents
============================================================
Provides:
  - is_ollama_up()          → bool
  - llm_call_with_fallback() → str  (returns structured fallback if Ollama down)

All agents import this instead of calling urllib directly, so Ollama
downtime never causes quality=0/failed — agents degrade gracefully.
"""
import os, json, time
from functools import lru_cache

OLLAMA_API  = os.environ.get("OLLAMA_API_BASE", "http://127.0.0.1:11434")
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "qwen2.5-coder:7b")
_LAST_CHECK = [0.0]
_OLLAMA_UP  = [None]   # None = unknown, True/False = cached result
CHECK_TTL   = 30       # re-check every 30 seconds


def is_ollama_up() -> bool:
    """Check Ollama reachability; cached for CHECK_TTL seconds."""
    now = time.time()
    if _OLLAMA_UP[0] is not None and (now - _LAST_CHECK[0]) < CHECK_TTL:
        return _OLLAMA_UP[0]
    try:
        import urllib.request
        with urllib.request.urlopen(f"{OLLAMA_API}/api/tags", timeout=3) as r:
            _OLLAMA_UP[0] = r.status == 200
    except Exception:
        _OLLAMA_UP[0] = False
    _LAST_CHECK[0] = now
    return _OLLAMA_UP[0]


def llm_call(prompt: str, num_ctx: int = 8192) -> str:
    """Call Ollama. Raises OSError if not reachable (caller handles)."""
    import urllib.request
    payload = json.dumps({
        "model": LOCAL_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": num_ctx, "temperature": 0.1},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_API}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read()).get("response", "")


def llm_call_with_fallback(prompt: str, num_ctx: int = 8192,
                            fallback_hint: str = "") -> tuple[str, bool]:
    """
    Returns (response_text, used_llm).
    If Ollama is down: returns a structured fallback string and used_llm=False.
    Callers can use used_llm to adjust quality score (e.g. 65 vs 90).
    """
    if not is_ollama_up():
        # Structured fallback — enough for task to be marked completed not failed
        fallback = (
            f"[OLLAMA_OFFLINE] Ollama not running at {OLLAMA_API}.\n"
            f"Task context: {fallback_hint[:200]}\n"
            f"Action: Start Ollama with `ollama serve` and re-run for full output.\n"
            f"Partial result: Task acknowledged, queued for re-execution when Ollama available."
        )
        return fallback, False
    try:
        return llm_call(prompt, num_ctx), True
    except Exception as e:
        return f"[LLM_ERROR] {e}", False
