"""
Template manager for local-agents project scaffolding.

Usage:
    from local_agents.templates import list_templates, get_template, scaffold

    # List available templates
    templates = list_templates()

    # Get metadata for a specific template
    meta = get_template("fastapi")

    # Scaffold a new project
    result = scaffold("fastapi", "/path/to/target", "my-api", author="Jane Doe")
    print(result["files_created"])
    print(result["commands_to_run"])
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

_TEMPLATES_DIR = Path(__file__).parent
_REGISTRY_PATH = _TEMPLATES_DIR / "registry.json"


def _load_registry() -> dict:
    with open(_REGISTRY_PATH) as f:
        return json.load(f)


def list_templates() -> dict[str, dict]:
    """Return all registered templates with their metadata.

    Returns:
        dict mapping template name to metadata dict with keys:
        dir, language, framework, description, post_scaffold.
    """
    return _load_registry()["templates"]


def get_template(name: str) -> dict:
    """Return metadata for a single template.

    Args:
        name: Template name (e.g. "fastapi", "nextjs").

    Returns:
        Metadata dict.

    Raises:
        KeyError: If the template name is not registered.
    """
    templates = list_templates()
    if name not in templates:
        available = ", ".join(sorted(templates))
        raise KeyError(f"Template '{name}' not found. Available: {available}")
    return templates[name]


def scaffold(
    name: str,
    target_dir: str,
    project_name: str,
    **vars: Any,
) -> dict:
    """Copy a template into target_dir and substitute {{placeholder}} variables.

    Args:
        name: Template name from registry (e.g. "fastapi").
        target_dir: Destination directory. Must not already exist.
        project_name: Primary project name — replaces {{name}} in all files
            and filenames.
        **vars: Additional variables to substitute, e.g. author="Jane".

    Returns:
        dict with keys:
            files_created (list[str]): Relative paths of every file written.
            commands_to_run (list[str]): Post-scaffold commands from registry.

    Raises:
        KeyError: Unknown template.
        FileExistsError: target_dir already exists.
    """
    meta = get_template(name)
    template_src = _TEMPLATES_DIR / meta["dir"]
    target = Path(target_dir)

    if target.exists():
        raise FileExistsError(f"Target directory already exists: {target}")

    # Build substitution context
    context: dict[str, str] = {"name": project_name, **{k: str(v) for k, v in vars.items()}}

    files_created: list[str] = []

    for src_path in sorted(template_src.rglob("*")):
        if src_path.is_dir():
            continue

        rel = src_path.relative_to(template_src)

        # Substitute {{name}} in path segments
        dest_rel = Path(*[_substitute(part, context) for part in rel.parts])
        dest_path = target / dest_rel
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # Read and substitute file content (text files only)
        try:
            content = src_path.read_text(encoding="utf-8")
            content = _substitute(content, context)
            dest_path.write_text(content, encoding="utf-8")
        except (UnicodeDecodeError, ValueError):
            # Binary file — copy as-is
            shutil.copy2(src_path, dest_path)

        files_created.append(str(dest_rel))

    return {
        "files_created": files_created,
        "commands_to_run": meta.get("post_scaffold", []),
    }


def _substitute(text: str, context: dict[str, str]) -> str:
    """Replace all {{key}} occurrences in text with context values."""
    def replacer(match: re.Match) -> str:
        key = match.group(1).strip()
        return context.get(key, match.group(0))

    return re.sub(r"\{\{(\w+)\}\}", replacer, text)
