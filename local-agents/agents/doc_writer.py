#!/usr/bin/env python3
"""
doc_writer.py — Documentation generation agent
================================================
Generates README files, docstrings, API docs, and inline comments
from code and task descriptions using local Ollama.

Entry point: run(task) -> dict
"""
import os, sys, json, re, time
from pathlib import Path

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

AGENT_META = {
    "name": "doc_writer",
    "version": 1,
    "capabilities": ["documentation", "readme", "api_docs", "docstrings"],
    "model": "qwen2.5-coder:7b",
    "input_schema": {
        "id": "int", "title": "str", "description": "str",
        "category": "str",
        "code": "str",       # optional: code to document
        "doc_type": "str",   # readme | docstrings | api_docs | comments
    },
    "output_schema": {
        "status": "str",
        "documentation": "str",
        "doc_type": "str",
        "quality": "int",
        "tokens_used": "int",
        "elapsed_s": "float",
    },
    "benchmark_score": None,
}

OLLAMA_API  = os.environ.get("OLLAMA_API_BASE", "http://127.0.0.1:11434")
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "qwen2.5-coder:7b")


def _llm_call(prompt: str, num_ctx: int = 8192) -> str:
    import urllib.request
    payload = json.dumps({
        "model": LOCAL_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": num_ctx, "temperature": 0.2},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_API}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read()).get("response", "")


def run(task: dict) -> dict:
    start    = time.time()
    title    = task.get("title", "")
    description = task.get("description", title)
    code     = task.get("code", "")
    doc_type = task.get("doc_type", "readme")

    if doc_type == "docstrings" and code:
        prompt = (
            f"Add comprehensive docstrings to this Python code.\n\n"
            f"CODE:\n```python\n{code[:4000]}\n```\n\n"
            f"Add Google-style docstrings to every function and class.\n"
            f"Include: Args, Returns, Raises, Examples sections.\n"
            f"Output the COMPLETE code with docstrings added.\n"
            f"Do NOT truncate."
        )
    elif doc_type == "api_docs":
        prompt = (
            f"Write API documentation for this module.\n\n"
            f"MODULE: {title}\nDESCRIPTION: {description}\n"
            + (f"CODE:\n```python\n{code[:3000]}\n```\n\n" if code else "\n")
            + f"Write markdown API docs with:\n"
            f"- Module overview\n"
            f"- Function signatures with parameters and return types\n"
            f"- Usage examples with code blocks\n"
            f"- Error handling notes\n"
        )
    else:  # readme
        prompt = (
            f"Write a README.md for this project or module.\n\n"
            f"PROJECT: {title}\nDESCRIPTION: {description}\n"
            + (f"CODE SAMPLE:\n```python\n{code[:2000]}\n```\n\n" if code else "\n")
            + f"Include:\n"
            f"## Overview\n## Installation\n## Usage\n## Examples\n## API Reference\n"
            f"## Contributing\n\n"
            f"Write concise, developer-friendly markdown. Include code examples."
        )

    try:
        raw = _llm_call(prompt)

        # Quality scoring
        quality = 40
        if len(raw) > 300:
            quality += 20
        if "##" in raw or "```" in raw:
            quality += 20
        if "example" in raw.lower() or "usage" in raw.lower():
            quality += 10
        if len(raw) > 1000:
            quality += 10
        quality = min(100, quality)

        return {
            "status": "done",
            "documentation": raw,
            "output": raw,
            "doc_type": doc_type,
            "quality": quality,
            "tokens_used": len(raw) // 4,
            "elapsed_s": round(time.time() - start, 1),
            "agent": "doc_writer",
        }
    except Exception as e:
        return {
            "status": "failed",
            "documentation": "",
            "output": str(e),
            "doc_type": doc_type,
            "quality": 0,
            "tokens_used": 0,
            "elapsed_s": round(time.time() - start, 1),
            "agent": "doc_writer",
            "error": str(e),
        }
