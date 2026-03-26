#!/usr/bin/env python3
"""
researcher.py — Code, web, and docs research agent
====================================================
Searches the local codebase AND external sources (web, GitHub, PyPI, NPM).
All external calls use stdlib only (urllib) — no third-party deps required.

Modes (task["mode"]):
  web      — DuckDuckGo Instant Answer API
  github   — GitHub public repo/code search
  docs     — fetch a URL and return plain text
  pypi     — PyPI package metadata
  npm      — NPM registry metadata
  combined — web + github together (default when mode omitted)
  local    — local codebase grep only (original behaviour)

Entry point: run(task) -> dict
"""
import os, sys, json, re, subprocess, time
import urllib.request, urllib.parse
from pathlib import Path
from typing import Optional

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

AGENT_META = {
    "name": "researcher",
    "version": 2,
    "capabilities": [
        "research", "code_search", "context_assembly",
        "web_search", "github_search", "docs_fetch",
        "pypi_info", "npm_info",
    ],
    "model": "qwen2.5-coder:7b",
    "input_schema": {
        "id": "int", "title": "str", "description": "str",
        "category": "str",
        "search_query": "str",    # optional: specific pattern to search
        "search_path": "str",     # optional: path to search in (local mode)
        "mode": "str",            # web|github|docs|pypi|npm|combined|local
        "url": "str",             # for mode=docs
        "language": "str",        # optional: language filter for github_search_code
        "n": "int",               # max results (default 5)
    },
    "output_schema": {
        "status": "str",
        "output": "str",          # synthesized human-readable summary
        "sources": "any",         # raw results list or dict
        "findings": "list",       # local code findings [{file, line, snippet}]
        "quality": "int",
        "tokens_used": "int",
        "elapsed_s": "float",
        "agent": "str",
    },
    "benchmark_score": None,
}

BOS        = os.environ.get("BOS_HOME", os.path.expanduser("~/local-agents-os"))
MAX_FINDINGS = 10
MAX_SNIPPET  = 300
_HEADERS   = {"User-Agent": "local-agent-runtime/2.0 (research agent)"}


# ---------------------------------------------------------------------------
# WebSearchTool — DuckDuckGo Instant Answer API (no key needed)
# ---------------------------------------------------------------------------

def web_search(query: str, n: int = 5) -> list:
    """
    Search DuckDuckGo Instant Answer API (free, no key needed).
    Returns list of {title, url, snippet}.
    """
    url = (
        "https://api.duckduckgo.com/?q="
        + urllib.parse.quote(query)
        + "&format=json&no_html=1&skip_disambig=1"
    )
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        results = []
        # AbstractText is the top summary hit
        if data.get("AbstractText"):
            results.append({
                "title":   data.get("Heading", ""),
                "url":     data.get("AbstractURL", ""),
                "snippet": data["AbstractText"],
            })
        # RelatedTopics contain additional results
        for topic in data.get("RelatedTopics", []):
            if len(results) >= n:
                break
            if "Text" in topic and "FirstURL" in topic:
                results.append({
                    "title":   topic["Text"][:100],
                    "url":     topic["FirstURL"],
                    "snippet": topic["Text"],
                })
        return results[:n]
    except Exception as exc:
        return [{"error": str(exc), "query": query}]


# ---------------------------------------------------------------------------
# GitHubSearchTool — public GitHub API (no auth for public repos)
# ---------------------------------------------------------------------------

def github_search_repos(query: str, n: int = 5) -> list:
    """Search GitHub repos via public API. Returns [{name, url, description, stars, language}]."""
    url = (
        "https://api.github.com/search/repositories?q="
        + urllib.parse.quote(query)
        + f"&sort=stars&per_page={n}"
    )
    try:
        req = urllib.request.Request(url, headers={**_HEADERS, "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        results = []
        for item in data.get("items", [])[:n]:
            results.append({
                "name":        item.get("full_name", ""),
                "url":         item.get("html_url", ""),
                "description": (item.get("description") or "")[:200],
                "stars":       item.get("stargazers_count", 0),
                "language":    item.get("language", ""),
            })
        return results
    except Exception as exc:
        return [{"error": str(exc), "query": query}]


def github_search_code(query: str, language: Optional[str] = None, n: int = 5) -> list:
    """Search GitHub code via public API. Returns [{file, repo, url, snippet}]."""
    q = query
    if language:
        q += f" language:{language}"
    url = (
        "https://api.github.com/search/code?q="
        + urllib.parse.quote(q)
        + f"&per_page={n}"
    )
    try:
        req = urllib.request.Request(url, headers={**_HEADERS, "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        results = []
        for item in data.get("items", [])[:n]:
            results.append({
                "file":    item.get("name", ""),
                "repo":    item.get("repository", {}).get("full_name", ""),
                "url":     item.get("html_url", ""),
                "snippet": item.get("path", ""),
            })
        return results
    except Exception as exc:
        return [{"error": str(exc), "query": q}]


# ---------------------------------------------------------------------------
# DocsFetchTool — fetch URL → plain text; PyPI / NPM metadata
# ---------------------------------------------------------------------------

def fetch_url(url: str, max_chars: int = 3000) -> str:
    """Fetch a URL and return plain text (HTML tags stripped)."""
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        # Strip script/style blocks
        raw = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", " ", raw, flags=re.S | re.I)
        # Strip remaining tags
        text = re.sub(r"<[^>]+>", " ", raw)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception as exc:
        return f"[fetch_url error: {exc}]"


def fetch_pypi_info(package: str) -> dict:
    """Fetch package metadata from PyPI JSON API."""
    url = f"https://pypi.org/pypi/{urllib.parse.quote(package)}/json"
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        info = data.get("info", {})
        return {
            "name":        info.get("name", package),
            "version":     info.get("version", ""),
            "summary":     info.get("summary", ""),
            "home_page":   info.get("home_page", "") or info.get("project_url", ""),
            "license":     info.get("license", ""),
            "requires_python": info.get("requires_python", ""),
            "author":      info.get("author", ""),
        }
    except Exception as exc:
        return {"error": str(exc), "package": package}


def fetch_npm_info(package: str) -> dict:
    """Fetch package metadata from NPM registry."""
    url = f"https://registry.npmjs.org/{urllib.parse.quote(package, safe='@/')}"
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        latest_version = data.get("dist-tags", {}).get("latest", "")
        latest_info    = data.get("versions", {}).get(latest_version, {})
        return {
            "name":        data.get("name", package),
            "version":     latest_version,
            "description": data.get("description", ""),
            "homepage":    data.get("homepage", ""),
            "license":     latest_info.get("license", data.get("license", "")),
            "keywords":    data.get("keywords", [])[:10],
        }
    except Exception as exc:
        return {"error": str(exc), "package": package}


# ---------------------------------------------------------------------------
# Local codebase search (original behaviour, preserved)
# ---------------------------------------------------------------------------

def _search_code(pattern: str, path: str = BASE_DIR) -> list:
    """Search for pattern in Python files. Returns [{file, line, snippet}]."""
    findings = []
    try:
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", "-m", "3", pattern, path],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines()[:MAX_FINDINGS]:
            parts = line.split(":", 2)
            if len(parts) >= 3:
                findings.append({
                    "file":    parts[0],
                    "line":    parts[1],
                    "snippet": parts[2].strip()[:MAX_SNIPPET],
                })
    except Exception:
        pass
    return findings


def _extract_keywords(title: str, description: str) -> list:
    """Extract searchable keywords from task description."""
    text = (title + " " + description).lower()
    keywords = re.findall(r'\b[a-z_][a-z_0-9]{3,}\b', text)
    stopwords = {
        "with", "that", "this", "from", "into", "using", "should", "will",
        "have", "function", "write", "create", "implement", "make", "build",
    }
    return [k for k in keywords if k not in stopwords][:5]


# ---------------------------------------------------------------------------
# Synthesis helper
# ---------------------------------------------------------------------------

def synthesize_findings(query: str, results) -> str:
    """Turn search results into an actionable findings summary (bullet list)."""
    lines = [f"Research results for: {query}", ""]

    def _add_list(items, label):
        if not items:
            return
        lines.append(f"### {label}")
        for item in items:
            if "error" in item:
                lines.append(f"  - [error] {item['error']}")
                continue
            title   = item.get("title") or item.get("name") or item.get("file") or ""
            url     = item.get("url") or item.get("home_page") or item.get("homepage") or ""
            snippet = item.get("snippet") or item.get("description") or item.get("summary") or ""
            stars   = item.get("stars")
            star_str = f"  ({stars} stars)" if stars is not None else ""
            lines.append(f"  - {title}{star_str}: {snippet[:150]}")
            if url:
                lines.append(f"    {url}")
        lines.append("")

    if isinstance(results, dict):
        _add_list(results.get("web", []),    "Web")
        _add_list(results.get("github", []), "GitHub")
        _add_list(results.get("code", []),   "GitHub Code")
    elif isinstance(results, list):
        _add_list(results, "Results")
    elif isinstance(results, str):
        lines.append(results[:1000])

    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# search_and_store — web+github results → SemanticMemory
# ---------------------------------------------------------------------------

def search_and_store(query: str, memory_store) -> dict:
    """
    Run web + GitHub search, store each result as a fact in SemanticMemory,
    and return a structured summary.

    memory_store must be a SemanticMemory instance (or duck-typed equivalent
    with a store_fact(key, value, source, project_id) method).
    """
    web_results = web_search(query, n=5)
    gh_results  = github_search_repos(query, n=5)

    stored = 0
    for i, item in enumerate(web_results):
        if "error" not in item:
            key   = f"web:{query[:40]}:{i}"
            value = json.dumps({"title": item.get("title", ""), "url": item.get("url", ""),
                                "snippet": item.get("snippet", "")[:300]})
            memory_store.store_fact(key, value, source="web_search")
            stored += 1

    for i, item in enumerate(gh_results):
        if "error" not in item:
            key   = f"github:{query[:40]}:{i}"
            value = json.dumps({"name": item.get("name", ""), "url": item.get("url", ""),
                                "description": item.get("description", "")[:200],
                                "stars": item.get("stars", 0)})
            memory_store.store_fact(key, value, source="github_search")
            stored += 1

    combined = {"web": web_results, "github": gh_results}
    summary  = synthesize_findings(query, combined)
    return {
        "query":   query,
        "stored":  stored,
        "summary": summary,
        "sources": combined,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(task: dict) -> dict:
    start = time.time()
    query = task.get("description", task.get("title", ""))
    mode  = task.get("mode", "combined")
    n     = int(task.get("n", 5))

    results  = None
    findings = []  # local code findings

    if mode == "web":
        results = web_search(query, n=n)

    elif mode == "github":
        results = github_search_repos(query, n=n)

    elif mode == "github_code":
        results = github_search_code(query, language=task.get("language"), n=n)

    elif mode == "docs":
        url     = task.get("url", query)
        results = fetch_url(url)

    elif mode == "pypi":
        results = fetch_pypi_info(query)

    elif mode == "npm":
        results = fetch_npm_info(query)

    elif mode == "local":
        # Original local-codebase-only behaviour
        search_path = task.get("search_path", BASE_DIR)
        queries = []
        if task.get("search_query"):
            queries.append(task["search_query"])
        queries.extend(_extract_keywords(task.get("title", ""), query))
        all_findings = []
        for q in queries[:3]:
            all_findings.extend(_search_code(q, search_path))
            if len(all_findings) >= MAX_FINDINGS:
                break
        seen = set()
        for f in all_findings:
            key = f"{f['file']}:{f['line']}"
            if key not in seen:
                seen.add(key)
                findings.append(f)
        results = findings

    else:  # combined (default)
        web = web_search(query, n=3)
        gh  = github_search_repos(query, n=3)
        results = {"web": web, "github": gh}

    synthesis = synthesize_findings(query, results)

    # Quality heuristic: higher when we got real results
    if isinstance(results, dict):
        total_hits = sum(
            len([r for r in v if "error" not in r])
            for v in results.values() if isinstance(v, list)
        )
    elif isinstance(results, list):
        total_hits = len([r for r in results if isinstance(r, dict) and "error" not in r])
    else:
        total_hits = 1 if results and "error" not in str(results) else 0
    quality = min(100, 50 + total_hits * 5)

    return {
        "status":     "done",
        "output":     synthesis,
        "sources":    results,
        "findings":   findings,
        "quality":    quality,
        "tokens_used": 0,
        "elapsed_s":  round(time.time() - start, 2),
        "agent":      "researcher",
    }
