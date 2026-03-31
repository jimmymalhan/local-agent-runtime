#!/usr/bin/env python3
"""
ollama_guard.py — Backward-compatible shim. All logic in nexus_inference.py.
"""
from agents.nexus_inference import is_engine_up, infer as _infer


def is_ollama_up() -> bool:
    return is_engine_up()


def llm_call(prompt: str, num_ctx: int = 8192) -> str:
    result, ok = _infer(prompt, num_ctx, mode="code")
    if not ok:
        raise OSError("Nexus inference engine offline")
    return result


def llm_call_with_fallback(prompt: str, num_ctx: int = 8192,
                            fallback_hint: str = "") -> tuple:
    return _infer(prompt, num_ctx, hint=fallback_hint, mode="code")
