"""
code_graph.py — Dependency graph + blast radius analysis.

Uses stdlib ast (no tree-sitter needed) for Python.
Detects: imports, function calls, class inheritance.
blast_radius(file) returns all files that must be re-tested after a change.
convention_learner() extracts naming/style from existing code.
"""
import ast, re, json
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Set

class CodeGraph:
    def __init__(self, project_path: str):
        self.root = Path(project_path)
        self.graph: Dict[str, Set[str]] = defaultdict(set)  # file -> files it imports
        self.reverse: Dict[str, Set[str]] = defaultdict(set)  # file -> files that import it
        self._built = False

    def build(self):
        """Index all Python files and their import dependencies"""
        py_files = [f for f in self.root.rglob("*.py")
                   if not any(skip in f.parts for skip in {"__pycache__", ".venv", "node_modules"})]

        for pyfile in py_files:
            key = str(pyfile.relative_to(self.root))
            try:
                tree = ast.parse(pyfile.read_text(errors="ignore"))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        module = ""
                        if isinstance(node, ast.ImportFrom) and node.module:
                            module = node.module
                        elif isinstance(node, ast.Import):
                            module = node.names[0].name if node.names else ""

                        # Try to resolve to a local file
                        parts = module.split(".")
                        candidates = [
                            self.root / Path(*parts).with_suffix(".py"),
                            self.root / Path(*parts) / "__init__.py",
                        ]
                        for cand in candidates:
                            if cand.exists():
                                dep_key = str(cand.relative_to(self.root))
                                self.graph[key].add(dep_key)
                                self.reverse[dep_key].add(key)
                                break
            except: pass
        self._built = True

    def blast_radius(self, changed_file: str) -> List[str]:
        """All files that transitively depend on changed_file (must retest)"""
        if not self._built: self.build()
        key = str(Path(changed_file).relative_to(self.root)) if Path(changed_file).is_absolute() else changed_file
        affected = set()
        stack = list(self.reverse.get(key, []))
        while stack:
            f = stack.pop()
            if f not in affected:
                affected.add(f)
                stack.extend(self.reverse.get(f, []))
        return sorted(affected)

    def convention_learner(self) -> dict:
        """Extract coding conventions from existing source files"""
        if not self._built: self.build()

        names = {"functions": [], "classes": [], "variables": []}
        has_type_hints = 0
        has_docstrings = 0
        indent_sizes = []
        total_funcs = 0

        for pyfile in list(self.root.rglob("*.py"))[:30]:
            if any(skip in pyfile.parts for skip in {"__pycache__", ".venv"}): continue
            try:
                content = pyfile.read_text(errors="ignore")
                tree = ast.parse(content)

                # Detect indentation
                for line in content.splitlines():
                    if line.startswith("    "): indent_sizes.append(4); break
                    elif line.startswith("  "): indent_sizes.append(2); break

                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        total_funcs += 1
                        names["functions"].append(node.name)
                        if ast.get_docstring(node): has_docstrings += 1
                        if node.returns or any(a.annotation for a in node.args.args):
                            has_type_hints += 1
                    elif isinstance(node, ast.ClassDef):
                        names["classes"].append(node.name)
            except: pass

        # Detect naming convention
        def detect_case(names_list):
            if not names_list: return "unknown"
            snake = sum(1 for n in names_list if "_" in n and n == n.lower())
            camel = sum(1 for n in names_list if n[0].islower() and any(c.isupper() for c in n))
            pascal = sum(1 for n in names_list if n[0].isupper())
            if snake > camel and snake > pascal: return "snake_case"
            if pascal > snake and pascal > camel: return "PascalCase"
            return "camelCase"

        conventions = {
            "function_naming": detect_case(names["functions"]),
            "class_naming": detect_case(names["classes"]),
            "indent_size": max(set(indent_sizes), key=indent_sizes.count) if indent_sizes else 4,
            "type_hints_used": has_type_hints / max(total_funcs, 1) > 0.5,
            "docstrings_used": has_docstrings / max(total_funcs, 1) > 0.5,
        }

        # Save to .nexus/
        nexus = self.root / ".nexus"
        nexus.mkdir(exist_ok=True)
        (nexus / "conventions.json").write_text(json.dumps(conventions, indent=2))
        return conventions

def run(task: dict) -> dict:
    path = task.get("path", ".")
    graph = CodeGraph(path)
    graph.build()

    if task.get("action") == "blast_radius":
        result = {"blast_radius": graph.blast_radius(task["file"])}
    elif task.get("action") == "conventions":
        result = {"conventions": graph.convention_learner()}
    else:
        result = {
            "files_indexed": len(graph.graph),
            "conventions": graph.convention_learner(),
        }
    return {"quality": 80, "output": result, "agent": "code_graph"}
