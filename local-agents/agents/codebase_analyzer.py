#!/usr/bin/env python3
"""codebase_analyzer.py -- Static codebase structure and quality analyzer."""
import ast
import os
import re
import sys
import time
from pathlib import Path

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

AGENT_META = {
    "name": "codebase_analyzer",
    "version": 1,
    "capabilities": ["analyze", "structure"],
    "model": "local-static",
    "benchmark_score": None,
}

SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv"}
LANG_MAP = {".py": "Python", ".ts": "TypeScript", ".js": "JavaScript", ".go": "Go"}


def _iter_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            yield Path(dirpath) / fname


def _count_lines(fpath):
    try:
        return fpath.read_text(encoding="utf-8", errors="replace").count("\n")
    except OSError:
        return 0


def _python_symbols(fpath):
    try:
        source = fpath.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except Exception:
        return {"functions": 0, "classes": 0}
    functions = sum(
        1 for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    classes = sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    )
    return {"functions": functions, "classes": classes}


def analyze_codebase(root_path):
    root = Path(root_path)
    if not root.exists():
        return {"file_count": 0, "line_count": 0, "languages": {}, "modules": [], "hotspots": []}

    languages = {}
    file_count = 0
    line_count = 0
    modules = []
    hotspots_raw = []

    for fpath in _iter_files(root):
        if fpath.suffix not in LANG_MAP:
            continue
        file_count += 1
        lang = LANG_MAP[fpath.suffix]
        languages[lang] = languages.get(lang, 0) + 1
        lines = _count_lines(fpath)
        line_count += lines
        try:
            rel = str(fpath.relative_to(root))
        except ValueError:
            rel = str(fpath)
        modules.append(rel)
        if fpath.suffix == ".py":
            syms = _python_symbols(fpath)
            total = syms["functions"] + syms["classes"]
            if total > 0:
                hotspots_raw.append({"file": rel, "total_symbols": total, "lines": lines})

    hotspots = sorted(hotspots_raw, key=lambda h: h["total_symbols"], reverse=True)[:10]
    return {
        "file_count": file_count,
        "line_count": line_count,
        "languages": languages,
        "modules": sorted(modules),
        "hotspots": hotspots,
    }


def run(task):
    start = time.time()
    root_path = task.get("codebase_path", task.get("path", "."))
    analysis = analyze_codebase(root_path)
    file_count = analysis.get("file_count", 0)
    line_count = analysis.get("line_count", 0)
    quality = min(100, max(0, 50 + min(file_count, 30) + min(line_count // 100, 20)))
    return {
        "status": "done",
        "file_count": file_count,
        "line_count": line_count,
        "languages": analysis.get("languages", {}),
        "modules": analysis.get("modules", [])[:20],
        "hotspots": analysis.get("hotspots", []),
        "quality": quality,
        "tokens_used": 0,
        "elapsed_s": round(time.time() - start, 3),
        "agent": "codebase_analyzer",
    }


if __name__ == "__main__":
    import json
    path = sys.argv[1] if len(sys.argv) > 1 else "."
    print(json.dumps(run({"codebase_path": path}), indent=2))
