#!/usr/bin/env python3
"""
multi_editor.py -- Multi-file atomic edit agent.

Provides MultiEditor class with:
  edit_files(plan)                   atomic multi-file string substitution
  refactor(old_symbol, new_symbol)   rename across .py/.ts/.js
  insert_after(file, anchor, code)   insert code block after anchor line
  delete_block(file, start, end)     delete lines between two regex patterns
  run(task)                          dispatcher for all actions

Module-level run(task) for router compatibility.
"""
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

BASE_DIR = str(Path(__file__).parent.parent)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

AGENT_META = {
    "name": "multi_editor",
    "version": 1,
    "capabilities": ["multi_edit", "refactor", "rename", "insert", "delete"],
    "model": "local",
    "benchmark_score": None,
}


class MultiEditor:
    """Atomic multi-file editor with validate-then-apply and rollback."""

    # ------------------------------------------------------------------
    # edit_files
    # ------------------------------------------------------------------

    def edit_files(self, plan: List[Dict]) -> Dict:
        """
        Apply a list of string-substitution edits atomically.

        Each plan item: {file, old, new, description}
          file        : path to the target file
          old         : exact string that must exist in the file
          new         : replacement string
          description : human-readable label (optional)

        Validates every old string exists before touching any file.
        Rolls back all changes if any step fails.
        """
        errors: List[str] = []

        # Phase 1: validate
        for i, item in enumerate(plan):
            fp = item.get("file", "")
            old = item.get("old", "")
            desc = item.get("description", f"item {i}")
            if not fp:
                errors.append(f"[{i}] missing 'file'")
                continue
            if not old:
                errors.append(f"[{i}] missing 'old' (file={fp})")
                continue
            try:
                content = Path(fp).read_text(encoding="utf-8")
            except FileNotFoundError:
                errors.append(f"[{i}] file not found: {fp}")
                continue
            except OSError as exc:
                errors.append(f"[{i}] cannot read {fp}: {exc}")
                continue
            if old not in content:
                errors.append(f"[{i}] ({desc}): old string not found in {fp}")

        if errors:
            return {
                "status": "failed",
                "files_changed": [],
                "errors": errors,
                "output": "Validation failed -- no files modified.\n" + "\n".join(errors),
            }

        # Phase 2: snapshot
        snapshots: Dict[str, str] = {}
        for item in plan:
            fp = item["file"]
            if fp not in snapshots:
                snapshots[fp] = Path(fp).read_text(encoding="utf-8")

        # Phase 3: apply in memory
        current: Dict[str, str] = dict(snapshots)
        files_changed: List[str] = []
        apply_errors: List[str] = []

        for i, item in enumerate(plan):
            fp = item["file"]
            old = item["old"]
            new = item.get("new", "")
            desc = item.get("description", f"edit {i}")
            if old not in current[fp]:
                apply_errors.append(
                    f"[{i}] ({desc}): old string disappeared mid-apply in {fp}"
                )
                break
            current[fp] = current[fp].replace(old, new, 1)
            if fp not in files_changed:
                files_changed.append(fp)

        if apply_errors:
            for fp, original in snapshots.items():
                Path(fp).write_text(original, encoding="utf-8")
            return {
                "status": "failed",
                "files_changed": [],
                "errors": apply_errors,
                "output": "Apply failed -- rolled back.\n" + "\n".join(apply_errors),
            }

        # Phase 4: write
        write_errors: List[str] = []
        written: List[str] = []
        try:
            for fp, text in current.items():
                if text != snapshots[fp]:
                    Path(fp).write_text(text, encoding="utf-8")
                    written.append(fp)
        except OSError as exc:
            write_errors.append(str(exc))
            for fp in written:
                Path(fp).write_text(snapshots[fp], encoding="utf-8")
            return {
                "status": "failed",
                "files_changed": [],
                "errors": write_errors,
                "output": "Write failed -- rolled back.\n" + "\n".join(write_errors),
            }

        return {
            "status": "done",
            "files_changed": files_changed,
            "errors": [],
            "output": (
                f"Applied {len(plan)} edit(s) across "
                f"{len(files_changed)} file(s): {files_changed}"
            ),
        }

    # ------------------------------------------------------------------
    # refactor
    # ------------------------------------------------------------------

    def refactor(
        self,
        old_symbol: str,
        new_symbol: str,
        files: Optional[List[str]] = None,
    ) -> Dict:
        """
        Rename old_symbol to new_symbol across .py, .ts, and .js files.

        Uses whole-word regex matching to avoid partial renames.
        If files is None, discovers all matching files under cwd.
        """
        if not old_symbol:
            return {
                "status": "failed",
                "files_changed": [],
                "errors": ["old_symbol is required"],
                "output": "old_symbol is required",
            }

        if files is None:
            cwd = Path.cwd()
            found: List[str] = []
            for ext in ("**/*.py", "**/*.ts", "**/*.js"):
                found.extend(str(p) for p in cwd.glob(ext) if p.is_file())
            files = found

        if not files:
            return {
                "status": "done",
                "files_changed": [],
                "errors": [],
                "output": "No .py/.ts/.js files found.",
            }

        pattern = re.compile(r"\b" + re.escape(old_symbol) + r"\b")
        plan_items: List[Dict[str, str]] = []

        for fp in files:
            try:
                content = Path(fp).read_text(encoding="utf-8")
            except OSError:
                continue
            if pattern.search(content):
                plan_items.append(
                    {
                        "file": fp,
                        "old_content": content,
                        "new_content": pattern.sub(new_symbol, content),
                    }
                )

        if not plan_items:
            return {
                "status": "done",
                "files_changed": [],
                "errors": [],
                "output": f"Symbol '{old_symbol}' not found in any file.",
            }

        snapshots_r = {item["file"]: item["old_content"] for item in plan_items}
        files_changed_r: List[str] = []
        try:
            for item in plan_items:
                Path(item["file"]).write_text(item["new_content"], encoding="utf-8")
                files_changed_r.append(item["file"])
        except OSError as exc:
            for fp, original in snapshots_r.items():
                try:
                    Path(fp).write_text(original, encoding="utf-8")
                except OSError:
                    pass
            return {
                "status": "failed",
                "files_changed": [],
                "errors": [str(exc)],
                "output": f"Write failed -- rolled back. Error: {exc}",
            }

        return {
            "status": "done",
            "files_changed": files_changed_r,
            "errors": [],
            "output": (
                f"Renamed '{old_symbol}' -> '{new_symbol}' "
                f"in {len(files_changed_r)} file(s): {files_changed_r}"
            ),
        }

    # ------------------------------------------------------------------
    # insert_after
    # ------------------------------------------------------------------

    def insert_after(self, file: str, anchor: str, code: str) -> Dict:
        """
        Insert code immediately after the first line containing anchor.
        Indentation of the anchor line is matched in the inserted block.
        """
        if not file:
            return {"status": "failed", "files_changed": [], "errors": ["file required"],
                    "output": "file is required"}
        if not anchor:
            return {"status": "failed", "files_changed": [], "errors": ["anchor required"],
                    "output": "anchor is required"}

        try:
            original = Path(file).read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"status": "failed", "files_changed": [], "errors": [f"Not found: {file}"],
                    "output": f"File not found: {file}"}
        except OSError as exc:
            return {"status": "failed", "files_changed": [], "errors": [str(exc)],
                    "output": str(exc)}

        lines = original.splitlines(keepends=True)
        anchor_idx: Optional[int] = None
        for i, line in enumerate(lines):
            if anchor in line:
                anchor_idx = i
                break

        if anchor_idx is None:
            return {
                "status": "failed",
                "files_changed": [],
                "errors": [f"Anchor '{anchor}' not found in {file}"],
                "output": f"Anchor not found in {file}",
            }

        anchor_line = lines[anchor_idx]
        indent = len(anchor_line) - len(anchor_line.lstrip())
        indent_str = anchor_line[:indent]

        indented = "\n".join(indent_str + cl for cl in code.splitlines())
        if not indented.endswith("\n"):
            indented += "\n"

        new_lines = lines[: anchor_idx + 1] + [indented] + lines[anchor_idx + 1 :]

        try:
            Path(file).write_text("".join(new_lines), encoding="utf-8")
        except OSError as exc:
            return {"status": "failed", "files_changed": [], "errors": [str(exc)],
                    "output": str(exc)}

        return {
            "status": "done",
            "files_changed": [file],
            "errors": [],
            "output": f"Inserted code after '{anchor}' in {file}",
        }

    # ------------------------------------------------------------------
    # delete_block
    # ------------------------------------------------------------------

    def delete_block(self, file: str, start_pattern: str, end_pattern: str) -> Dict:
        """
        Delete lines from the first line matching start_pattern up to and
        including the first subsequent line matching end_pattern.
        """
        if not file:
            return {"status": "failed", "files_changed": [], "errors": ["file required"],
                    "output": "file is required"}

        try:
            original = Path(file).read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"status": "failed", "files_changed": [], "errors": [f"Not found: {file}"],
                    "output": f"File not found: {file}"}
        except OSError as exc:
            return {"status": "failed", "files_changed": [], "errors": [str(exc)],
                    "output": str(exc)}

        lines = original.splitlines(keepends=True)
        start_re = re.compile(start_pattern)
        end_re = re.compile(end_pattern)

        start_idx: Optional[int] = None
        end_idx: Optional[int] = None

        for i, line in enumerate(lines):
            if start_idx is None and start_re.search(line):
                start_idx = i
            elif start_idx is not None and end_re.search(line):
                end_idx = i
                break

        if start_idx is None:
            return {
                "status": "failed",
                "files_changed": [],
                "errors": [f"start_pattern '{start_pattern}' not found in {file}"],
                "output": f"start_pattern not found in {file}",
            }
        if end_idx is None:
            return {
                "status": "failed",
                "files_changed": [],
                "errors": [f"end_pattern '{end_pattern}' not found after start in {file}"],
                "output": f"end_pattern not found after start_pattern in {file}",
            }

        new_lines = lines[:start_idx] + lines[end_idx + 1 :]
        try:
            Path(file).write_text("".join(new_lines), encoding="utf-8")
        except OSError as exc:
            return {"status": "failed", "files_changed": [], "errors": [str(exc)],
                    "output": str(exc)}

        return {
            "status": "done",
            "files_changed": [file],
            "errors": [],
            "output": f"Deleted block lines {start_idx + 1} to {end_idx + 1} in {file}",
        }

    # ------------------------------------------------------------------
    # run -- dispatcher
    # ------------------------------------------------------------------

    def run(self, task: Dict) -> Dict:
        """
        Dispatcher. task["action"] in: edit, refactor, rename, insert, delete
        """
        t0 = time.time()
        action = task.get("action", "edit")

        if action == "edit":
            result = self.edit_files(task.get("plan", []))
        elif action in ("refactor", "rename"):
            result = self.refactor(
                old_symbol=task.get("old_symbol", ""),
                new_symbol=task.get("new_symbol", ""),
                files=task.get("files", None),
            )
        elif action == "insert":
            result = self.insert_after(
                file=task.get("file", ""),
                anchor=task.get("anchor", ""),
                code=task.get("code", ""),
            )
        elif action == "delete":
            result = self.delete_block(
                file=task.get("file", ""),
                start_pattern=task.get("start_pattern", ""),
                end_pattern=task.get("end_pattern", ""),
            )
        else:
            result = {
                "status": "failed",
                "files_changed": [],
                "errors": [f"Unknown action: '{action}'"],
                "output": (
                    f"Unknown action '{action}'. "
                    "Use: edit, refactor, rename, insert, delete"
                ),
            }

        quality = 90 if result.get("status") == "done" else 0
        return {
            "status": result.get("status", "failed"),
            "output": result.get("output", ""),
            "files_changed": result.get("files_changed", []),
            "errors": result.get("errors", []),
            "quality": quality,
            "tokens_used": 0,
            "elapsed_s": round(time.time() - t0, 3),
            "agent": "multi_editor",
        }


# ---------------------------------------------------------------------------
# Module-level run() -- router calls agents.multi_editor.run(task)
# ---------------------------------------------------------------------------

_instance = MultiEditor()


def run(task: Dict) -> Dict:
    """Module-level entry point -- delegates to MultiEditor().run()."""
    return _instance.run(task)
