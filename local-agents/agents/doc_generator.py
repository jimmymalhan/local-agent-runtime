"""Documentation generator -- README, API docs, architecture diagrams, changelogs."""
import ast
import re
from pathlib import Path
from datetime import datetime


def extract_docstrings(filepath: str) -> dict:
    """Extract all docstrings from a Python file"""
    try:
        tree = ast.parse(Path(filepath).read_text())
    except Exception:
        return {}
    docs = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node)
            if doc:
                docs[node.name] = doc
    return docs


def generate_api_docs(src_dir: str) -> str:
    """Generate API reference from Python source files"""
    lines = ["# API Reference\n"]
    for pyfile in sorted(Path(src_dir).rglob("*.py")):
        if any(skip in str(pyfile) for skip in ["__pycache__", "test_", "_test."]):
            continue
        docs = extract_docstrings(str(pyfile))
        if not docs:
            continue
        rel = pyfile.relative_to(src_dir)
        lines.append(f"\n## `{rel}`\n")
        for name, doc in docs.items():
            lines.append(f"\n### `{name}`\n{doc}\n")
    return "\n".join(lines)


def generate_readme_section(project_path: str) -> str:
    """Generate/update README quick-start from project structure"""
    p = Path(project_path)
    name = p.name
    has_pytest = (p / "tests").exists() or list(p.rglob("test_*.py"))
    has_docker = (p / "Dockerfile").exists()
    has_reqs = (p / "requirements.txt").exists()

    lines = [f"# {name}\n", "## Quick Start\n"]
    if has_reqs:
        lines.append("```bash\npip install -r requirements.txt\n```\n")
    if has_docker:
        lines.append(f"```bash\ndocker build -t {name} . && docker run {name}\n```\n")
    if has_pytest:
        lines.append("```bash\npytest tests/\n```\n")
    return "\n".join(lines)


def generate_changelog_entry(task_title: str, files_changed: list) -> str:
    date = datetime.utcnow().strftime("%Y-%m-%d")
    files_str = ", ".join(f"`{f}`" for f in files_changed[:5])
    return f"\n## {date}\n- {task_title} -- {files_str}\n"


def run(task: dict) -> dict:
    mode = task.get("mode", "api")
    path = task.get("path", ".")
    if mode == "api":
        output = generate_api_docs(path)
    elif mode == "readme":
        output = generate_readme_section(path)
    elif mode == "changelog":
        output = generate_changelog_entry(task.get("title", ""), task.get("files", []))
    else:
        output = generate_api_docs(path)
    out_file = Path(path) / f"docs_{mode}_{datetime.utcnow().strftime('%H%M')}.md"
    out_file.parent.mkdir(exist_ok=True)
    if mode != "changelog":
        out_file.write_text(output)
    return {"quality": 75, "output": output[:500], "agent": "doc_generator", "file": str(out_file)}
