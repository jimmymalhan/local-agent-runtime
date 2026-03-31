#!/usr/bin/env python3
"""
researcher.py — Code and pattern research agent
=================================================
Searches the local codebase for patterns, reads relevant files,
and assembles context for other agents. Does NOT call external APIs.
For web research, see benchmarks/frustration_research.py.

Entry point: run(task) -> dict
"""
import os, sys, json, re, subprocess, time
from pathlib import Path

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

AGENT_META = {
    "name": "researcher",
    "version": 1,
    "capabilities": ["research", "code_search", "context_assembly"],
    "model": "nexus-local",
    "input_schema": {
        "id": "int", "title": "str", "description": "str",
        "category": "str",
        "search_query": "str",   # optional: specific pattern to search
        "search_path": "str",    # optional: path to search in
    },
    "output_schema": {
        "status": "str",
        "findings": "list",      # [{file, line, snippet}]
        "context": "str",        # assembled context for other agents
        "quality": "int",
        "tokens_used": "int",
        "elapsed_s": "float",
    },
    "benchmark_score": None,
}

BOS = os.environ.get("BOS_HOME", os.path.expanduser("~/local-agents-os"))
MAX_FINDINGS = 10
MAX_SNIPPET  = 300


def _search_code(pattern: str, path: str = BASE_DIR) -> list:
    """Search for pattern in Python files. Returns [{file, line, snippet}]."""
    findings = []
    try:
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", "-m", "3", pattern, path],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines()[:MAX_FINDINGS]:
            parts = line.split(":", 2)
            if len(parts) >= 3:
                findings.append({
                    "file": parts[0],
                    "line": parts[1],
                    "snippet": parts[2].strip()[:MAX_SNIPPET],
                })
    except Exception:
        pass
    return findings


def _extract_keywords(title: str, description: str) -> list:
    """Extract searchable keywords from task description."""
    text = (title + " " + description).lower()
    # Extract function names, class names, technical terms
    keywords = re.findall(r'\b[a-z_][a-z_0-9]{3,}\b', text)
    # Filter common words
    stopwords = {"with", "that", "this", "from", "into", "using", "should", "will",
                 "have", "function", "write", "create", "implement", "make", "build"}
    return [k for k in keywords if k not in stopwords][:5]


def run(task: dict) -> dict:
    start       = time.time()
    title       = task.get("title", "")
    description = task.get("description", title)
    query       = task.get("search_query", "")
    search_path = task.get("search_path", BASE_DIR)

    # Build search queries
    queries = []
    if query:
        queries.append(query)
    queries.extend(_extract_keywords(title, description))

    all_findings = []
    for q in queries[:3]:
        found = _search_code(q, search_path)
        all_findings.extend(found)
        if len(all_findings) >= MAX_FINDINGS:
            break

    # Deduplicate by file+line
    seen = set()
    unique_findings = []
    for f in all_findings:
        key = f"{f['file']}:{f['line']}"
        if key not in seen:
            seen.add(key)
            unique_findings.append(f)

    # Assemble context string
    context_parts = [f"Research for: {title}"]
    for f in unique_findings[:5]:
        context_parts.append(f"  [{f['file']}:{f['line']}] {f['snippet']}")
    context = "\n".join(context_parts)

    quality = min(100, 40 + len(unique_findings) * 10)

    return {
        "status": "done",
        "findings": unique_findings[:MAX_FINDINGS],
        "context": context,
        "quality": quality,
        "tokens_used": 0,
        "elapsed_s": round(time.time() - start, 2),
        "agent": "researcher",
    }
