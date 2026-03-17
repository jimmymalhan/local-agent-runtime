#!/usr/bin/env python3
"""Quality delta harness.

Compares current local output quality against a baseline by scoring:
- Plan accuracy (do referenced file paths exist?)
- Code correctness (basic syntax check)
- Hallucination rate (non-existent file references)

Reads the latest session output and state/progress.json for context.
"""

import ast
import json
import os
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
LATEST_RESPONSE = REPO_ROOT / "logs" / "latest-response.md"
PROGRESS_PATH = REPO_ROOT / "state" / "progress.json"
BASELINE_PATH = REPO_ROOT / "tests" / "fixtures" / "quality-benchmarks.json"


def load_latest_output():
    """Read the latest session output."""
    if LATEST_RESPONSE.exists():
        return LATEST_RESPONSE.read_text(errors="ignore")
    return ""


def load_progress():
    """Read current progress state."""
    if PROGRESS_PATH.exists():
        try:
            return json.loads(PROGRESS_PATH.read_text(errors="ignore"))
        except json.JSONDecodeError:
            return {}
    return {}


def load_baseline():
    """Load quality benchmark baselines."""
    if BASELINE_PATH.exists():
        try:
            return json.loads(BASELINE_PATH.read_text(errors="ignore"))
        except json.JSONDecodeError:
            return {}
    return {}


def extract_file_paths(text):
    """Extract file path references from output text."""
    patterns = [
        r'`([a-zA-Z0-9_./-]+\.[a-zA-Z0-9]+)`',
        r'(?:^|\s)((?:[a-zA-Z0-9_-]+/)+[a-zA-Z0-9_.-]+\.[a-zA-Z0-9]+)',
    ]
    paths = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            candidate = match.group(1)
            if len(candidate) > 3 and '.' in candidate:
                paths.add(candidate)
    return paths


def score_plan_accuracy(text, target_repo=None):
    """Score plan accuracy: do referenced file paths actually exist?"""
    repo = pathlib.Path(target_repo) if target_repo else REPO_ROOT
    paths = extract_file_paths(text)
    if not paths:
        return 100, "No file paths referenced", []

    existing = []
    missing = []
    for p in paths:
        full = repo / p
        if full.exists():
            existing.append(p)
        else:
            # Also check relative to common subdirectories
            found = False
            for subdir in ["", "scripts/", "roles/", "skills/", "config/", "state/", "tests/"]:
                if (repo / subdir / p).exists():
                    existing.append(p)
                    found = True
                    break
            if not found:
                missing.append(p)

    total = len(existing) + len(missing)
    score = int((len(existing) / total) * 100) if total > 0 else 100
    detail = f"{len(existing)}/{total} paths exist"
    return score, detail, missing


def extract_code_blocks(text):
    """Extract code blocks from markdown-style output."""
    blocks = re.findall(r'```(?:python|py)?\n(.*?)```', text, re.DOTALL)
    return blocks


def score_code_correctness(text):
    """Score code correctness via syntax check on extracted code blocks."""
    blocks = extract_code_blocks(text)
    if not blocks:
        return 100, "No code blocks to check", []

    errors = []
    valid = 0
    for i, block in enumerate(blocks):
        try:
            ast.parse(block)
            valid += 1
        except SyntaxError as e:
            errors.append(f"Block {i + 1}: {e.msg} (line {e.lineno})")

    total = len(blocks)
    score = int((valid / total) * 100) if total > 0 else 100
    detail = f"{valid}/{total} blocks have valid syntax"
    return score, detail, errors


def score_hallucination_rate(text, target_repo=None):
    """Score hallucination rate: references to non-existent files."""
    repo = pathlib.Path(target_repo) if target_repo else REPO_ROOT
    paths = extract_file_paths(text)
    if not paths:
        return 100, "No references to check", []

    hallucinated = []
    for p in paths:
        full = repo / p
        if not full.exists():
            # Check common subdirectories
            found = any(
                (repo / subdir / p).exists()
                for subdir in ["", "scripts/", "roles/", "skills/", "config/", "state/", "tests/"]
            )
            if not found:
                hallucinated.append(p)

    total = len(paths)
    real = total - len(hallucinated)
    score = int((real / total) * 100) if total > 0 else 100
    detail = f"{len(hallucinated)}/{total} references are hallucinated"
    return score, detail, hallucinated


def composite_score(plan, code, hallucination):
    """Weighted composite: plan 40%, code 30%, hallucination 30%."""
    return int(plan * 0.40 + code * 0.30 + hallucination * 0.30)


def compare_against_baseline(scores, baseline):
    """Compare current scores against baseline benchmarks."""
    deltas = {}
    baseline_scores = baseline.get("baseline_scores", {})
    for key, current in scores.items():
        base = baseline_scores.get(key, 70)
        deltas[key] = {
            "current": current,
            "baseline": base,
            "delta": current - base,
            "status": "above" if current >= base else "below",
        }
    return deltas


def main():
    target_repo = sys.argv[1] if len(sys.argv) > 1 else str(REPO_ROOT)

    output = load_latest_output()
    if not output:
        print("No latest output found at", LATEST_RESPONSE)
        sys.exit(1)

    progress = load_progress()
    baseline = load_baseline()

    plan_score, plan_detail, plan_missing = score_plan_accuracy(output, target_repo)
    code_score, code_detail, code_errors = score_code_correctness(output)
    hall_score, hall_detail, hall_items = score_hallucination_rate(output, target_repo)
    comp = composite_score(plan_score, code_score, hall_score)

    scores = {
        "plan_accuracy": plan_score,
        "code_correctness": code_score,
        "hallucination_rate": hall_score,
        "composite": comp,
    }

    result = {
        "target_repo": target_repo,
        "source": str(LATEST_RESPONSE),
        "task": progress.get("task", "unknown"),
        "scores": scores,
        "details": {
            "plan_accuracy": plan_detail,
            "code_correctness": code_detail,
            "hallucination_rate": hall_detail,
        },
        "issues": {
            "missing_paths": plan_missing,
            "syntax_errors": code_errors,
            "hallucinated_refs": hall_items,
        },
    }

    if baseline:
        result["baseline_comparison"] = compare_against_baseline(scores, baseline)

    print(json.dumps(result, indent=2))

    # Exit code reflects quality
    if comp >= 70:
        sys.exit(0)
    elif comp >= 40:
        print(f"\nWARNING: Composite score {comp} is below 70 (weak quality)", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"\nERROR: Composite score {comp} is below 40 (failing quality)", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
