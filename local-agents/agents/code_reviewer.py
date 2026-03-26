#!/usr/bin/env python3
"""
code_reviewer.py -- Deep static analysis code review agent
===========================================================
Analyzes Python/TypeScript files for:
  - Code smells: long functions (>50 lines), deep nesting (>4 levels),
    magic numbers, duplicate code blocks
  - Missing error handling: bare except, silent exception suppression
  - Security: hardcoded secrets, SQL injection patterns, unsafe eval/exec

Entry point: run(task) -> dict
Actions: "file" | "diff" | "pr"
"""
import ast
import os
import re
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

AGENT_META = {
    "name": "code_reviewer",
    "version": 2,
    "capabilities": ["review", "code_review", "pr_review", "security_scan", "smell_detection"],
    "model": "local-static",
    "input_schema": {
        "action": "str",
        "filepath": "str",
        "diff_text": "str",
        "pr_number": "int",
    },
    "output_schema": {
        "issues": "list",
        "score": "int",
        "summary": "str",
        "status": "str",
        "quality": "int",
        "elapsed_s": "float",
    },
    "benchmark_score": None,
}

_SECURITY_PATTERNS = [
    (
        r'(?i)(password|passwd|pwd|secret|token|api_key|apikey|auth_key)\s*=\s*["\'][^"\']{4,}["\']',
        "security", "high",
        "Hardcoded credential detected.",
        "Use environment variables or a secrets manager instead.",
    ),
    (
        r'(?i)(execute|cursor\.execute)\s*\(\s*["\'].*%[s]',
        "security", "high",
        "Potential SQL injection via %%-formatting in execute().",
        "Use parameterised queries: cursor.execute(sql, (param,))",
    ),
    (
        r'(?i)(execute|cursor\.execute)\s*\(\s*f["\']',
        "security", "high",
        "Potential SQL injection via f-string in execute().",
        "Use parameterised queries: cursor.execute(sql, (param,))",
    ),
    (
        r'\beval\s*\(',
        "security", "high",
        "Unsafe eval() -- arbitrary code execution risk.",
        "Avoid eval(); use json.loads() or ast.literal_eval().",
    ),
    (
        r'\bexec\s*\(',
        "security", "high",
        "Unsafe exec() -- arbitrary code execution risk.",
        "Avoid exec(); refactor to use importlib or explicit function calls.",
    ),
    (
        r'subprocess\.[^\n]+shell\s*=\s*True',
        "security", "medium",
        "shell=True in subprocess is a command injection risk.",
        "Pass a list of arguments with shell=False.",
    ),
    (
        r'\bos\.system\s*\(',
        "security", "medium",
        "os.system() is vulnerable to shell injection.",
        "Use subprocess.run([...], shell=False) instead.",
    ),
]

_ERROR_HANDLING_PATTERNS = [
    (
        r'\bexcept\s*:',
        "error_handling", "medium",
        "Bare except: catches ALL exceptions including KeyboardInterrupt.",
        "Specify exception types: except (ValueError, TypeError) as e:",
    ),
    (
        r'\bexcept\s+Exception\s*:',
        "error_handling", "low",
        "Catching broad Exception hides unexpected errors.",
        "Catch specific exceptions; re-raise or log unexpected ones.",
    ),
]


def _ast_issues(source):
    issues = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        issues.append({
            "line": exc.lineno or 1,
            "severity": "high",
            "type": "syntax",
            "message": "SyntaxError: %s" % exc.msg,
            "suggestion": "Fix the syntax error before proceeding.",
        })
        return issues

    lines = source.splitlines()
    func_names = {}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end_line = getattr(node, "end_lineno", node.lineno)
            func_len = end_line - node.lineno
            if func_len > 50:
                issues.append({
                    "line": node.lineno,
                    "severity": "medium",
                    "type": "code_smell",
                    "message": "Function '%s' is %d lines long (limit: 50)." % (node.name, func_len),
                    "suggestion": "Break it into smaller, single-responsibility functions.",
                })
            if node.name in func_names:
                issues.append({
                    "line": node.lineno,
                    "severity": "medium",
                    "type": "duplicate_code",
                    "message": "Function '%s' defined again (first at line %d)." % (
                        node.name, func_names[node.name]),
                    "suggestion": "Remove or rename the duplicate definition.",
                })
            else:
                func_names[node.name] = node.lineno

        if isinstance(node, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
            depth = _nesting_depth(node)
            if depth > 4:
                issues.append({
                    "line": node.lineno,
                    "severity": "medium",
                    "type": "code_smell",
                    "message": "Nesting depth %d exceeds limit of 4 at line %d." % (depth, node.lineno),
                    "suggestion": "Extract inner blocks into helper functions or use early returns.",
                })

        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            val = node.value
            if val not in (0, 1, -1, 2, True, False):
                line_text = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
                if not re.match(r'^[A-Z_][A-Z0-9_]*\s*=', line_text):
                    issues.append({
                        "line": node.lineno,
                        "severity": "low",
                        "type": "magic_number",
                        "message": "Magic number %r at line %d." % (val, node.lineno),
                        "suggestion": "Replace with a named constant.",
                    })

    return issues


def _nesting_depth(node, _depth=1):
    control = (ast.If, ast.For, ast.While, ast.With, ast.Try)
    max_depth = _depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, control):
            d = _nesting_depth(child, _depth + 1)
            if d > max_depth:
                max_depth = d
    return max_depth


def _regex_issues(source):
    issues = []
    all_patterns = _SECURITY_PATTERNS + _ERROR_HANDLING_PATTERNS
    for lineno, line in enumerate(source.splitlines(), start=1):
        for pattern, issue_type, severity, message, suggestion in all_patterns:
            if re.search(pattern, line):
                issues.append({
                    "line": lineno,
                    "severity": severity,
                    "type": issue_type,
                    "message": message,
                    "suggestion": suggestion,
                })
                break
    return issues


def _duplicate_block_issues(source):
    issues = []
    lines = source.splitlines()
    windows = {}
    for i in range(len(lines) - 3):
        block = "\n".join(lines[i:i + 4]).strip()
        if len(block) < 40:
            continue
        windows.setdefault(block, []).append(i + 1)
    reported = set()
    for block, occurrences in windows.items():
        if len(occurrences) > 1 and block not in reported:
            reported.add(block)
            for lineno in occurrences[1:]:
                issues.append({
                    "line": lineno,
                    "severity": "medium",
                    "type": "duplicate_code",
                    "message": "Duplicate 4-line block (first at line %d)." % occurrences[0],
                    "suggestion": "Extract the repeated block into a shared helper function.",
                })
    return issues


def _compute_score(issues):
    deductions = 0
    for issue in issues:
        sev = issue.get("severity", "low")
        if sev == "high":
            deductions += 15
        elif sev == "medium":
            deductions += 7
        else:
            deductions += 2
    return max(0, 100 - deductions)


def _build_summary(issues, score, source_name):
    if not issues:
        return "%s: No issues found. Score: %d/100." % (source_name, score)
    by_type = {}
    for iss in issues:
        t = iss["type"]
        by_type[t] = by_type.get(t, 0) + 1
    parts = ["%d %s" % (count, t) for t, count in sorted(by_type.items())]
    verdict = "clean" if score >= 80 else "needs attention" if score >= 50 else "critical"
    return "%s: %d issue(s) -- %s. Score: %d/100 (%s)." % (
        source_name, len(issues), ", ".join(parts), score, verdict
    )


class CodeReviewer:
    """
    Deep static analysis code reviewer for Python and TypeScript files.

    Methods
    -------
    review_file(filepath)   -> dict  -- analyse a file on disk
    review_diff(diff_text)  -> dict  -- analyse changed lines from a git diff
    review_pr(pr_number)    -> dict  -- fetch PR diff via gh, review, post comment
    run(task)               -> dict  -- dispatcher: action in ["file","diff","pr"]
    """

    def review_file(self, filepath):
        """
        Analyse a Python or TypeScript file for code smells, error-handling
        gaps, and security issues.

        Returns dict with keys: issues, score, summary
        """
        path = Path(filepath)
        if not path.exists():
            return {"issues": [], "score": 0, "summary": "File not found: %s" % filepath}
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"issues": [], "score": 0, "summary": "Cannot read file: %s" % exc}
        issues = self._analyze_source(source)
        score = _compute_score(issues)
        return {"issues": issues, "score": score, "summary": _build_summary(issues, score, path.name)}

    def review_diff(self, diff_text):
        """
        Review a git diff, focusing only on added lines (lines starting with '+').

        Returns dict with keys: issues, score, summary
        """
        if not diff_text or not diff_text.strip():
            return {"issues": [], "score": 100, "summary": "Empty diff -- nothing to review."}

        added_lines = []
        current_new_lineno = 0
        for raw_line in diff_text.splitlines():
            hunk_match = re.match(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', raw_line)
            if hunk_match:
                current_new_lineno = int(hunk_match.group(1)) - 1
                continue
            if raw_line.startswith("+++") or raw_line.startswith("---"):
                continue
            if raw_line.startswith("+"):
                current_new_lineno += 1
                added_lines.append((current_new_lineno, raw_line[1:]))
            elif not raw_line.startswith("-"):
                current_new_lineno += 1

        if not added_lines:
            return {"issues": [], "score": 100, "summary": "Diff contains no added lines."}

        first_lineno = added_lines[0][0]
        pseudo_lines = [""] * (first_lineno - 1)
        for lineno, text in added_lines:
            while len(pseudo_lines) < lineno - 1:
                pseudo_lines.append("")
            pseudo_lines.append(text)
        pseudo_source = "\n".join(pseudo_lines)

        issues = self._analyze_source(pseudo_source)
        added_linenos = {ln for ln, _ in added_lines}
        issues = [i for i in issues if i["line"] in added_linenos]
        score = _compute_score(issues)
        return {"issues": issues, "score": score, "summary": _build_summary(issues, score, "diff")}

    def review_pr(self, pr_number):
        """
        Fetch PR diff via `gh pr diff`, review it, and post a comment via `gh pr comment`.

        Returns dict with keys: issues, score, summary, comment_posted, pr_number
        """
        try:
            result = subprocess.run(
                ["gh", "pr", "diff", str(pr_number)],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                return {
                    "issues": [], "score": 0, "comment_posted": False, "pr_number": pr_number,
                    "summary": "Failed to fetch PR #%d diff: %s" % (pr_number, result.stderr.strip()),
                }
            diff_text = result.stdout
        except FileNotFoundError:
            return {
                "issues": [], "score": 0, "comment_posted": False, "pr_number": pr_number,
                "summary": "gh CLI not found. Install GitHub CLI to use review_pr().",
            }
        except subprocess.TimeoutExpired:
            return {
                "issues": [], "score": 0, "comment_posted": False, "pr_number": pr_number,
                "summary": "Timeout fetching diff for PR #%d." % pr_number,
            }

        review = self.review_diff(diff_text)
        comment_lines = [
            "## Code Review -- PR #%d" % pr_number, "",
            "**Score:** %d/100" % review["score"],
            "**Summary:** %s" % review["summary"], "",
        ]
        if review["issues"]:
            comment_lines += [
                "### Issues", "",
                "| Line | Severity | Type | Message | Suggestion |",
                "|------|----------|------|---------|------------|",
            ]
            for iss in review["issues"][:30]:
                comment_lines.append("| %d | %s | %s | %s | %s |" % (
                    iss["line"], iss["severity"], iss["type"], iss["message"], iss["suggestion"]))
        else:
            comment_lines.append("No issues detected in changed lines.")

        comment_posted = False
        try:
            post = subprocess.run(
                ["gh", "pr", "comment", str(pr_number), "--body", "\n".join(comment_lines)],
                capture_output=True, text=True, timeout=30,
            )
            comment_posted = post.returncode == 0
        except Exception:
            comment_posted = False

        return {
            "issues": review["issues"],
            "score": review["score"],
            "summary": review["summary"],
            "comment_posted": comment_posted,
            "pr_number": pr_number,
        }

    def _analyze_source(self, source):
        issues = []
        issues.extend(_ast_issues(source))
        issues.extend(_regex_issues(source))
        issues.extend(_duplicate_block_issues(source))
        seen = set()
        unique = []
        for iss in issues:
            key = (iss["line"], iss["type"], iss["message"])
            if key not in seen:
                seen.add(key)
                unique.append(iss)
        severity_order = {"high": 0, "medium": 1, "low": 2}
        unique.sort(key=lambda i: (i["line"], severity_order.get(i["severity"], 9)))
        return unique


def run(task):
    """
    Agent router entry point. task["action"] in ["file", "diff", "pr"].
    """
    start = time.time()
    reviewer = CodeReviewer()
    action = task.get("action", "file")

    if action == "file":
        filepath = task.get("filepath", task.get("path", task.get("file", "")))
        result = reviewer.review_file(filepath)
    elif action == "diff":
        diff_text = task.get("diff_text", task.get("diff", ""))
        result = reviewer.review_diff(diff_text)
    elif action == "pr":
        pr_number = int(task.get("pr_number", task.get("pr", 0)))
        result = reviewer.review_pr(pr_number)
    else:
        result = {
            "issues": [], "score": 0,
            "summary": "Unknown action '%s'. Use 'file', 'diff', or 'pr'." % action,
        }

    elapsed = round(time.time() - start, 3)
    extra = {k: v for k, v in result.items() if k not in ("issues", "score", "summary")}
    return {
        "status": "done",
        "issues": result.get("issues", []),
        "score": result.get("score", 0),
        "summary": result.get("summary", ""),
        "quality": result.get("score", 0),
        "tokens_used": 0,
        "elapsed_s": elapsed,
        "agent": "code_reviewer",
        **extra,
    }
