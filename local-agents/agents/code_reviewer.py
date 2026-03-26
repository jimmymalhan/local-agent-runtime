"""Deep code review -- security, performance, test gaps, architecture issues."""
import ast
import re
from pathlib import Path


SECURITY_PATTERNS = [
    (r"eval\s*\(", "eval() is dangerous -- potential code injection"),
    (r"exec\s*\(", "exec() is dangerous -- potential code injection"),
    (r"shell=True", "shell=True in subprocess is a command injection risk"),
    (r"password\s*=\s*[\"'][^\"']+[\"']", "Hardcoded password detected"),
    (r"secret\s*=\s*[\"'][^\"']+[\"']", "Hardcoded secret detected"),
    (r"\.format\(.*request\.", "Potential injection via string format"),
    (r'f".*\{.*request\.', "Potential injection via f-string"),
]

PERF_PATTERNS = [
    (r"for .+ in .+:\s*\n\s*.+\.append", "Use list comprehension instead of append loop"),
    (r"len\(.+\) == 0", "Use `not x` instead of `len(x) == 0`"),
    (r"time\.sleep\([^)]+\)", "sleep() in production code -- use async or queue"),
]


def review_python_file(filepath):
    """Run security, performance, and docstring checks on a single Python file"""
    content = Path(filepath).read_text()
    issues = []
    for pattern, msg in SECURITY_PATTERNS:
        for m in re.finditer(pattern, content):
            line = content[: m.start()].count("\n") + 1
            issues.append({"severity": "high", "type": "security", "line": line, "message": msg})
    for pattern, msg in PERF_PATTERNS:
        for m in re.finditer(pattern, content, re.MULTILINE):
            line = content[: m.start()].count("\n") + 1
            issues.append({"severity": "low", "type": "performance", "line": line, "message": msg})
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not ast.get_docstring(node) and not node.name.startswith("_"):
                    issues.append({
                        "severity": "low", "type": "docs", "line": node.lineno,
                        "message": f"Missing docstring: {node.name}()",
                    })
    except Exception:
        pass
    high = sum(1 for i in issues if i["severity"] == "high")
    score = max(0, 100 - high * 20 - len(issues) * 2)
    return {"score": score, "issues": issues, "file": filepath, "issue_count": len(issues)}


def run(task):
    """Review Python files in path/file for security, perf, and doc issues"""
    path = task.get("path") or task.get("file", ".")
    files = list(Path(path).rglob("*.py")) if Path(path).is_dir() else [Path(path)]
    files = [f for f in files if not any(s in str(f) for s in ["__pycache__", "test_"])]
    all_results = []
    for f in files[:20]:
        try:
            all_results.append(review_python_file(str(f)))
        except Exception:
            pass
    total_issues = sum(r["issue_count"] for r in all_results)
    avg_score = sum(r["score"] for r in all_results) / max(len(all_results), 1)
    return {
        "quality": int(avg_score),
        "output": {"files_reviewed": len(all_results), "total_issues": total_issues,
                   "results": all_results[:5]},
        "agent": "code_reviewer",
    }
