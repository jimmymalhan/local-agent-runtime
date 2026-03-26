"""Multi-file coordinated edits -- apply changes atomically across files."""
import re
from pathlib import Path
from typing import Dict, List


def apply_rename(old_name, new_name, directory):
    """Rename a function/class/variable across all Python files"""
    changed = []
    for f in Path(directory).rglob("*.py"):
        if "__pycache__" in str(f):
            continue
        try:
            content = f.read_text()
            pattern = r"\b" + re.escape(old_name) + r"\b"
            new_content = re.sub(pattern, new_name, content)
            if new_content != content:
                f.write_text(new_content)
                changed.append(str(f))
        except Exception:
            pass
    return {"changed_files": changed, "count": len(changed)}


def apply_import_update(old_import, new_import, directory):
    """Update import statements across all files"""
    changed = []
    for f in Path(directory).rglob("*.py"):
        if "__pycache__" in str(f):
            continue
        try:
            content = f.read_text()
            new_content = content.replace(old_import, new_import)
            if new_content != content:
                f.write_text(new_content)
                changed.append(str(f))
        except Exception:
            pass
    return {"changed_files": changed}


def apply_edits(edits):
    """Apply list of {file, old_text, new_text} edits atomically with rollback"""
    backups: Dict[str, str] = {}
    changed = []
    try:
        for edit in edits:
            f = Path(edit["file"])
            if not f.exists():
                continue
            content = f.read_text()
            backups[str(f)] = content
            new_content = content.replace(edit["old_text"], edit["new_text"], 1)
            f.write_text(new_content)
            changed.append(str(f))
        return {"ok": True, "changed": changed}
    except Exception as e:
        for filepath, original in backups.items():
            Path(filepath).write_text(original)
        return {"ok": False, "error": str(e), "rolled_back": list(backups.keys())}


def run(task):
    """Execute multi-file edit action: rename, update_import, or edit"""
    action = task.get("action", "edit")
    if action == "rename":
        result = apply_rename(task["old_name"], task["new_name"], task.get("path", "."))
    elif action == "update_import":
        result = apply_import_update(task["old_import"], task["new_import"], task.get("path", "."))
    elif action == "edit":
        result = apply_edits(task.get("edits", []))
    else:
        result = {"error": f"Unknown action: {action}"}
    quality = 80 if result.get("ok", True) else 30
    return {"quality": quality, "output": result, "agent": "multi_editor"}
