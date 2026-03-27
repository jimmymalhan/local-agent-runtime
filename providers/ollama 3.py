"""
providers/ollama.py — Local inference via Ollama
=================================================
Wraps the existing agent_runner.py Ollama loop behind the NexusProvider interface.
Nexus routes here for all local inference. Users never call Ollama directly.

Default model: qwen2.5-coder:7b (or config.yaml override)
"""
from __future__ import annotations
import os, sys, time, json, subprocess
from pathlib import Path
from typing import Optional

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

from providers.base import NexusProvider, CompletionResult

# Default model — overridden by NEXUS_LOCAL_MODEL env var or config.yaml
_DEFAULT_MODEL = os.environ.get("NEXUS_LOCAL_MODEL", "qwen2.5-coder:7b")
_OLLAMA_URL    = os.environ.get("NEXUS_OLLAMA_URL", "http://localhost:11434")


def _ollama_available(url: str = _OLLAMA_URL) -> bool:
    """Check if the Ollama daemon is reachable."""
    try:
        import urllib.request
        with urllib.request.urlopen(f"{url}/api/tags", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


class OllamaProvider(NexusProvider):
    """
    Local inference provider via Ollama REST API.
    Used for 90%+ of all Nexus tasks — zero recurring cost.
    """

    def __init__(self, model: str = "", url: str = ""):
        self._model = model or _DEFAULT_MODEL
        self._url   = url or _OLLAMA_URL

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def is_local(self) -> bool:
        return True

    def available(self) -> bool:
        return _ollama_available(self._url)

    def complete(
        self,
        prompt: str,
        system: str = "",
        model: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.2,
        timeout: int = 120,
    ) -> CompletionResult:
        m = model or self._model
        start = time.time()
        try:
            # Try existing agent_runner first (production path with quality loop)
            runner_path = os.path.join(BASE_DIR, "agent_runner.py")
            if os.path.exists(runner_path):
                return self._via_agent_runner(prompt, system, m, temperature, timeout, start)
            # Fallback: direct Ollama REST call
            return self._via_rest(prompt, system, m, max_tokens, temperature, timeout, start)
        except Exception as e:
            return CompletionResult(
                text="", model=m, provider="ollama",
                elapsed_s=round(time.time() - start, 1),
                error=str(e),
            )

    def _via_agent_runner(self, prompt, system, model, temperature, timeout, start):
        """Use existing agent_runner.py Ollama loop for production-quality output."""
        task = {
            "title": prompt[:80],
            "description": prompt,
            "category": "code_gen",
            "type": "code_gen",
        }
        try:
            sys.path.insert(0, BASE_DIR)
            from agent_runner import run_agent
            result = run_agent(
                task=task,
                model=model,
                url=self._url,
                temperature=temperature,
                timeout=timeout,
            )
            return CompletionResult(
                text=result.get("output", ""),
                model=model,
                provider="ollama",
                tokens_used=result.get("tokens_used", 0),
                quality=result.get("quality", 0.0),
                elapsed_s=round(time.time() - start, 1),
                metadata={"status": result.get("status", "")},
            )
        except Exception as e:
            return self._via_rest(prompt, "", model, 4096, temperature, timeout, start)

    def _via_rest(self, prompt, system, model, max_tokens, temperature, timeout, start):
        """Direct Ollama REST API call — fallback when agent_runner unavailable."""
        import urllib.request
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = json.dumps({
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }).encode()
        req = urllib.request.Request(
            f"{self._url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        text = data.get("message", {}).get("content", "")
        toks = data.get("eval_count", 0) + data.get("prompt_eval_count", 0)
        return CompletionResult(
            text=text, model=model, provider="ollama",
            tokens_used=toks,
            elapsed_s=round(time.time() - start, 1),
        )
