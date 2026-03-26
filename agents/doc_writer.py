#!/usr/bin/env python3
"""
doc_writer.py — Documentation generation agent (v2)
=====================================================
Generates README files, docstrings, API docs, and inline comments
from code and task descriptions using local Ollama.

New capabilities (v2):
  - generate_api_docs(src_dir): extracts docstrings via ast, outputs markdown
  - generate_readme_section(project_path): auto-builds quick-start from stack
  - generate_changelog_entry(title, files): produces CHANGELOG.md entry
  - run(task) with mode=api|readme|changelog

Entry point: run(task) -> dict
"""
import ast
import os
import sys
import json
import re
import time
from pathlib import Path
from typing import Optional

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

AGENT_META = {
    "name": "doc_writer",
    "version": 2,
    "capabilities": ["documentation", "readme", "api_docs", "docstrings", "changelog"],
    "model": "qwen2.5-coder:7b",
    "input_schema": {
        "id": "int", "title": "str", "description": "str",
        "category": "str",
        "code": "str",       # optional: code to document
        "doc_type": "str",   # readme | docstrings | api_docs | comments
        "mode": "str",       # api | readme | changelog
        "src_dir": "str",    # for generate_api_docs
        "project_path": "str", # for generate_readme_section
        "files": "list",     # for generate_changelog_entry
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



def generate_api_docs(src_dir: str) -> str:
    """
    Extract docstrings from all Python files in src_dir via ast and
    produce a markdown API reference document.

    Args:
        src_dir: Path to directory containing Python source files.

    Returns:
        Markdown string with full API documentation.
    """
    src_path = Path(src_dir)
    if not src_path.exists():
        return f"# API Documentation\n\nDirectory not found: {src_dir}\n"

    sections = ["# API Documentation\n"]

    def _get_ann(node) -> Optional[str]:
        if node is None:
            return ""
        try:
            return ast.unparse(node)
        except Exception:
            return ""

    for py_file in sorted(src_path.rglob("*.py")):
        if py_file.name.startswith("_") and py_file.name != "__init__.py":
            continue
        try:
            source = py_file.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source)
        except Exception:
            continue

        module_doc = ast.get_docstring(tree)
        rel_path = py_file.relative_to(src_path) if src_path in py_file.parents else py_file.name
        sections.append(f"\n## `{rel_path}`\n")
        if module_doc:
            sections.append(f"{module_doc}\n")

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                cls_doc = ast.get_docstring(node) or ""
                sections.append(f"\n### Class `{node.name}`\n")
                if cls_doc:
                    sections.append(f"{cls_doc}\n")
                sections.append(f"**Line**: {node.lineno}\n")

                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        fn_doc = ast.get_docstring(item) or ""
                        args = [a.arg for a in item.args.args]
                        ret = _get_ann(item.returns)
                        sig = f"{item.name}({', '.join(args)})"
                        if ret:
                            sig += f" -> {ret}"
                        sections.append(f"\n#### `{sig}`\n")
                        if fn_doc:
                            sections.append(f"{fn_doc}\n")

            elif isinstance(node, ast.FunctionDef):
                # Top-level functions
                fn_doc = ast.get_docstring(node) or ""
                args = [a.arg for a in node.args.args]
                ret = _get_ann(node.returns)
                sig = f"{node.name}({', '.join(args)})"
                if ret:
                    sig += f" -> {ret}"
                sections.append(f"\n### `{sig}`\n")
                if fn_doc:
                    sections.append(f"{fn_doc}\n")
                else:
                    sections.append(f"*No docstring.*\n")

    return "\n".join(sections)


def generate_readme_section(project_path: str) -> str:
    """
    Auto-build a Quick Start README section by detecting the project stack.

    Detects: Python (requirements.txt / setup.py / pyproject.toml),
    Node.js (package.json), Docker (Dockerfile), and general structure.

    Args:
        project_path: Path to the project root directory.

    Returns:
        Markdown string with ## Quick Start section.
    """
    p = Path(project_path)
    if not p.exists():
        return f"# Quick Start\n\nProject path not found: {project_path}\n"

    lines = ["## Quick Start\n"]
    stack = []
    install_cmds = []
    run_cmds = []

    # Detect stack
    if (p / "requirements.txt").exists():
        stack.append("Python")
        install_cmds.append("pip install -r requirements.txt")
        reqs = (p / "requirements.txt").read_text()[:500]
        lines.append(f"**Python dependencies** (`requirements.txt`):\n```\n{reqs.strip()}\n```\n")
    if (p / "pyproject.toml").exists():
        stack.append("Python")
        install_cmds.append("pip install -e .")
    if (p / "setup.py").exists() and "Python" not in stack:
        stack.append("Python")
        install_cmds.append("python setup.py install")
    if (p / "package.json").exists():
        stack.append("Node.js")
        try:
            pkg = json.loads((p / "package.json").read_text())
            install_cmds.append("npm install")
            scripts = pkg.get("scripts", {})
            if "start" in scripts:
                run_cmds.append("npm start")
            if "dev" in scripts:
                run_cmds.append("npm run dev")
            if "test" in scripts:
                run_cmds.append("npm test")
        except Exception:
            pass
    if (p / "Dockerfile").exists():
        stack.append("Docker")
        run_cmds.append("docker build -t app . && docker run -p 8080:8080 app")
    if (p / "docker-compose.yml").exists() or (p / "docker-compose.yaml").exists():
        stack.append("Docker Compose")
        run_cmds.append("docker-compose up")

    if stack:
        lines.append(f"**Detected stack**: {', '.join(stack)}\n")

    if install_cmds:
        lines.append("### Installation\n```bash")
        lines.extend(install_cmds)
        lines.append("```\n")

    if run_cmds:
        lines.append("### Run\n```bash")
        lines.extend(run_cmds)
        lines.append("```\n")

    # Detect entry points
    for candidate in ["main.py", "app.py", "server.py", "cli.py", "run.py"]:
        if (p / candidate).exists():
            lines.append(f"\n**Entry point**: `{candidate}`\n")
            break

    # List top-level directories
    dirs = [d.name for d in p.iterdir() if d.is_dir() and not d.name.startswith(".")]
    if dirs:
        lines.append(f"\n**Project structure**:\n```")
        for d in sorted(dirs)[:8]:
            lines.append(f"  {d}/")
        lines.append("```\n")

    return "\n".join(lines)


def generate_changelog_entry(title: str, files: list) -> str:
    """
    Generate a CHANGELOG.md entry for a release or feature.

    Args:
        title: The change title (e.g. "feat(agents): new test generator").
        files: List of changed file paths.

    Returns:
        Markdown CHANGELOG entry string.
    """
    from datetime import datetime
    date_str = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"## [{date_str}] — {title}\n",
        "### Changes\n",
    ]
    if files:
        lines.append("**Files modified**:\n")
        for f in files[:20]:
            lines.append(f"- `{f}`")
        lines.append("")
    lines += [
        "### Notes\n",
        "- Generated by doc_writer agent\n",
    ]
    return "\n".join(lines)


def run(task: dict) -> dict:
    """
    Entry point for documentation generation.

    Modes (via task['mode'] or task['doc_type']):
      - api|api_docs: generate_api_docs(src_dir)
      - readme: generate_readme_section(project_path) or LLM readme
      - changelog: generate_changelog_entry(title, files)
      - docstrings: add docstrings to code via LLM
    """
    start    = time.time()
    title    = task.get("title", "")
    description = task.get("description", title)
    code     = task.get("code", "")
    doc_type = task.get("doc_type", task.get("mode", "readme"))

    # API docs mode: extract docstrings via ast
    src_dir = task.get("src_dir", "")
    if doc_type in ("api", "api_docs") and src_dir:
        doc = generate_api_docs(src_dir)
        quality = 60 + min(40, len(doc) // 100)
        return {
            "status": "done", "documentation": doc, "output": doc,
            "doc_type": "api_docs", "quality": min(100, quality),
            "tokens_used": 0, "elapsed_s": round(time.time() - start, 1),
            "agent": "doc_writer",
        }

    # README quick-start section mode
    project_path = task.get("project_path", "")
    if doc_type == "readme" and project_path:
        doc = generate_readme_section(project_path)
        quality = 70 + min(30, len(doc) // 50)
        return {
            "status": "done", "documentation": doc, "output": doc,
            "doc_type": "readme", "quality": min(100, quality),
            "tokens_used": 0, "elapsed_s": round(time.time() - start, 1),
            "agent": "doc_writer",
        }

    # Changelog mode
    if doc_type == "changelog":
        files = task.get("files", [])
        doc = generate_changelog_entry(title, files)
        return {
            "status": "done", "documentation": doc, "output": doc,
            "doc_type": "changelog", "quality": 80,
            "tokens_used": 0, "elapsed_s": round(time.time() - start, 1),
            "agent": "doc_writer",
        }

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
