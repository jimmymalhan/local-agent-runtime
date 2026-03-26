#!/usr/bin/env python3
"""
upgrade_agent.py — Gap Analysis + Agent Patcher
=================================================
Reads benchmark results (v{N}_compare.jsonl), finds categories where
local agents lose to Opus 4.6, applies targeted patches to agent_runner.py,
and increments the version header.

Pattern: benchmark → analyze → patch → re-benchmark
Each patch is surgical: find a specific string, replace with improved version.

Patches applied per failure mode:
  code_gen fail   → strengthen WRITE_FILE directive + 1-shot example
  bug_fix fail    → inject error-line extraction + minimal repro step
  scaffold fail   → reinforce multi-file planning + SCAFFOLD directive
  tdd fail        → enforce test-first order (RED before GREEN)
  arch fail       → add design-doc generation step before code
  refactor fail   → add DEDUP_CHECK + smell detection pre-pass
  e2e fail        → increase ultra-hard iteration limit + checkpoints

Usage:
  python3 upgrade_agent.py --from 4 --to 5
  python3 upgrade_agent.py --analyze 4       # show gaps only, no patch
"""
import os, sys, json, re, shutil, argparse
from datetime import datetime
from pathlib import Path
from collections import defaultdict

BASE_DIR       = str(Path(__file__).resolve().parent.parent)
AGENT_RUNNER   = os.path.join(BASE_DIR, "scripts", "agent_runner.py")
REPORTS_DIR    = os.path.join(BASE_DIR, "reports")
SKILLED_AGENTS = os.path.join(BASE_DIR, "skilled-agents")
UPGRADE_THRESHOLD = 5.0   # Opus must beat local by >5pts to require patch


# ── Results analysis ──────────────────────────────────────────────────────

def load_results(version: int) -> list:
    path = os.path.join(REPORTS_DIR, f"v{version}_compare.jsonl")
    if not os.path.exists(path):
        print(f"[ANALYZE] No results at {path}")
        return []
    out = []
    with open(path) as f:
        for line in f:
            try:
                out.append(json.loads(line.strip()))
            except Exception:
                pass
    return out


def analyze_gaps(version: int) -> dict:
    """Return {category: gap_score} where gap_score > 0 means Opus wins."""
    results = load_results(version)
    if not results:
        return {}
    cats = defaultdict(lambda: {"local_q": 0, "opus_q": 0, "count": 0})
    for r in results:
        cat = r.get("category", "unknown")
        cats[cat]["local_q"] += r.get("local_quality", 0)
        cats[cat]["opus_q"] += r.get("opus_quality", 0)
        cats[cat]["count"] += 1
    gaps = {}
    print(f"\n[ANALYZE] v{version} gap analysis:")
    for cat, d in sorted(cats.items()):
        n = max(d["count"], 1)
        local_avg = d["local_q"] / n
        opus_avg = d["opus_q"] / n
        gap = opus_avg - local_avg
        status = "UPGRADE NEEDED" if gap > UPGRADE_THRESHOLD else "ok"
        print(f"  {cat:12s}: local={local_avg:.1f}  opus={opus_avg:.1f}  "
              f"gap={gap:+.1f}  [{status}]")
        if gap > UPGRADE_THRESHOLD:
            gaps[cat] = gap
    return gaps


# ── Patch registry ────────────────────────────────────────────────────────

PATCHES = {
    "code_gen": [
        # Strengthen WRITE_FILE directive with 1-shot example in system prompt
        {
            "find": "WRITE_FILE: <path>",
            "replace": (
                "WRITE_FILE: <path>   (COMPLETE code only, no explanations, "
                "must include all imports + __main__ with 3+ assertions)"
            ),
            "description": "Strengthen WRITE_FILE directive for code_gen failures",
        },
    ],
    "bug_fix": [
        {
            "find": "Iterate   — up to",
            "replace": (
                "BugFix pre-pass: extract error line, write minimal repro, "
                "THEN fix. Iterate   — up to"
            ),
            "description": "Add bug fix pre-pass for bug_fix failures",
        },
    ],
    "scaffold": [
        {
            "find": "Flow per task:",
            "replace": (
                "Scaffold mode: plan all files first (list them), "
                "then WRITE_FILE each one before running. "
                "Flow per task:"
            ),
            "description": "Reinforce multi-file planning for scaffold failures",
        },
    ],
    "tdd": [
        {
            "find": "3. Iterate",
            "replace": (
                "TDD enforcement: ALWAYS write test file first (RED), "
                "verify it fails, THEN write impl (GREEN). "
                "3. Iterate"
            ),
            "description": "Enforce test-first order for TDD failures",
        },
    ],
    "arch": [
        {
            "find": "2. Context",
            "replace": (
                "Architecture pre-pass: write a 5-line design note "
                "(pattern, components, interfaces) before any code. "
                "2. Context"
            ),
            "description": "Add design note step for arch failures",
        },
    ],
    "refactor": [
        {
            "find": "1. Triage",
            "replace": (
                "Refactor pre-pass: identify code smells (duplicates, "
                "god class, magic numbers) before writing. "
                "1. Triage"
            ),
            "description": "Add smell detection pre-pass for refactor failures",
        },
    ],
    "e2e": [
        {
            "find": "MAX_ITERATIONS  = 12",
            "replace": "MAX_ITERATIONS  = 16      # E2E upgrade: more iterations",
            "description": "Increase iteration limit for E2E failures",
        },
    ],
}


def apply_patches(gaps: dict, from_version: int, to_version: int) -> bool:
    """Apply surgical patches to agent_runner.py for categories where local lost."""
    if not os.path.exists(AGENT_RUNNER):
        print(f"[PATCH] agent_runner.py not found at {AGENT_RUNNER}")
        return False

    with open(AGENT_RUNNER) as f:
        content = f.read()

    original = content
    patches_applied = []

    for cat, gap in gaps.items():
        cat_patches = PATCHES.get(cat, [])
        for patch in cat_patches:
            find = patch["find"]
            replace = patch["replace"]
            desc = patch["description"]
            if find in content:
                content = content.replace(find, replace, 1)
                patches_applied.append(desc)
                print(f"  [PATCH] Applied: {desc}")
            else:
                print(f"  [PATCH] Skip (pattern not found): {desc}")

    # Always update version header
    content = re.sub(
        r'(V\d+)(\s*—\s*iterative tool-use loop)',
        f"V{to_version}\\2",
        content, count=1
    )
    content = re.sub(
        r'(agent runner V)\d+',
        f"\\g<1>{to_version}",
        content
    )

    if content != original:
        # Backup before patching
        backup = f"{AGENT_RUNNER}.v{from_version}.bak"
        shutil.copy2(AGENT_RUNNER, backup)
        with open(AGENT_RUNNER, "w") as f:
            f.write(content)
        print(f"  [PATCH] agent_runner.py updated (v{from_version}→v{to_version})")
        print(f"  [PATCH] Backup saved: {backup}")
    else:
        print(f"  [PATCH] No changes to apply — agent_runner.py already optimal")

    # Log patches
    log_path = os.path.join(REPORTS_DIR, f"upgrade_v{from_version}_to_v{to_version}.json")
    with open(log_path, "w") as f:
        json.dump({
            "ts": datetime.now().isoformat(),
            "from_version": from_version,
            "to_version": to_version,
            "gaps": gaps,
            "patches_applied": patches_applied,
        }, f, indent=2)

    return len(patches_applied) > 0


def create_skilled_agents_dir(from_version: int, to_version: int):
    """Copy local-agents-v{from} to local-agents-v{to} with updated docs."""
    src = os.path.join(SKILLED_AGENTS, f"local-agents-v{from_version}")
    dst = os.path.join(SKILLED_AGENTS, f"local-agents-v{to_version}")
    if os.path.exists(src):
        shutil.copytree(src, dst, dirs_exist_ok=True)
        print(f"  [SKILLED] Copied {src} → {dst}")
    else:
        Path(dst).mkdir(parents=True, exist_ok=True)
        print(f"  [SKILLED] Created {dst}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_v", type=int, required=False)
    ap.add_argument("--to", dest="to_v", type=int, required=False)
    ap.add_argument("--analyze", type=int, metavar="VERSION",
                    help="Analyze gaps for a version without patching")
    args = ap.parse_args()

    if args.analyze:
        analyze_gaps(args.analyze)
        return

    if args.from_v is None or args.to_v is None:
        print("Usage: upgrade_agent.py --from N --to N+1")
        return

    print(f"\n[UPGRADE] v{args.from_v} → v{args.to_v}")
    gaps = analyze_gaps(args.from_v)
    if not gaps:
        print("[UPGRADE] No gaps found — local agents already beating Opus!")
        return

    applied = apply_patches(gaps, args.from_v, args.to_v)
    create_skilled_agents_dir(args.from_v, args.to_v)

    print(f"\n[UPGRADE] Complete: {'patches applied' if applied else 'no changes needed'}")
    print(f"[UPGRADE] Run: python3 bench_compare.py --version {args.to_v}")


if __name__ == "__main__":
    main()
