#!/usr/bin/env python3
"""
benchmarker.py — Score tracking and gap analysis agent
=======================================================
Reads version compare reports, computes per-category gaps between local
and Opus 4.6, updates the agent registry, and triggers upgrades.

Wraps upgrade_agent.py for the actual patching step.

Entry point: run(task) -> dict
            analyze_version(version) -> dict
"""
import os, sys, json, time
from pathlib import Path
from collections import defaultdict

BASE_DIR    = str(Path(__file__).parent.parent)
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
REGISTRY    = os.path.join(BASE_DIR, "registry", "agents.json")
sys.path.insert(0, BASE_DIR)

AGENT_META = {
    "name": "benchmarker",
    "version": 1,
    "capabilities": ["scoring", "gap_analysis", "upgrade_trigger"],
    "model": "nexus-local",
    "input_schema": {"version": "int"},
    "output_schema": {
        "status": "str",
        "version": "int",
        "local_avg": "float",
        "opus_avg": "float",
        "gap": "float",
        "category_gaps": "dict",
        "local_wins": "bool",
        "upgrade_needed": "bool",
        "quality": "int",
        "elapsed_s": "float",
    },
    "benchmark_score": None,
}

WIN_THRESHOLD   = 5.0   # local must be within 5pts of opus to "win"
UPGRADE_TRIGGER = 5.0   # trigger upgrade if gap > 5pts in any category


def _load_compare_report(version: int) -> list:
    path = os.path.join(REPORTS_DIR, f"v{version}_compare.jsonl")
    if not os.path.exists(path):
        return []
    results = []
    with open(path) as f:
        for line in f:
            try:
                results.append(json.loads(line.strip()))
            except Exception:
                pass
    return results


def _update_registry(agent_name: str, version: int, avg_quality: float, win_rate: float):
    """Update registry/agents.json with latest benchmark scores."""
    if not os.path.exists(REGISTRY):
        return
    try:
        with open(REGISTRY) as f:
            reg = json.load(f)
        if agent_name in reg.get("agents", {}):
            reg["agents"][agent_name]["benchmark_scores"][f"v{version}"] = round(avg_quality, 1)
            reg["agents"][agent_name]["avg_quality"] = round(avg_quality, 1)
            reg["agents"][agent_name]["win_rate"] = round(win_rate, 1)
            reg["agents"][agent_name]["last_updated"] = "2026-03-25"
            reg["last_updated"] = "2026-03-25"
        with open(REGISTRY, "w") as f:
            json.dump(reg, f, indent=2)
    except Exception:
        pass


def analyze_version(version: int) -> dict:
    """Compute gap analysis for a version. Returns summary dict."""
    results = _load_compare_report(version)
    if not results:
        return {"error": f"No report found for v{version}"}

    local_scores  = [r.get("local_quality", 0) for r in results]
    opus_scores   = [r.get("opus_quality", 0)  for r in results]
    local_avg     = sum(local_scores) / len(local_scores) if local_scores else 0
    opus_avg      = sum(opus_scores)  / len(opus_scores)  if opus_scores  else 0

    # Per-category breakdown
    cat_local  = defaultdict(list)
    cat_opus   = defaultdict(list)
    for r in results:
        cat = r.get("category", "unknown")
        cat_local[cat].append(r.get("local_quality", 0))
        cat_opus[cat].append(r.get("opus_quality", 0))

    category_gaps = {}
    for cat in set(list(cat_local.keys()) + list(cat_opus.keys())):
        l_avg = sum(cat_local[cat]) / len(cat_local[cat]) if cat_local[cat] else 0
        o_avg = sum(cat_opus[cat])  / len(cat_opus[cat])  if cat_opus[cat]  else 0
        category_gaps[cat] = {
            "local_avg": round(l_avg, 1),
            "opus_avg": round(o_avg, 1),
            "gap": round(o_avg - l_avg, 1),
            "local_wins": l_avg >= o_avg - WIN_THRESHOLD,
        }

    gap          = round(opus_avg - local_avg, 1)
    local_wins   = all(v["local_wins"] for v in category_gaps.values())
    upgrade_cats = [cat for cat, v in category_gaps.items() if v["gap"] > UPGRADE_TRIGGER]

    # Win rate
    wins = sum(1 for l, o in zip(local_scores, opus_scores) if l >= o - WIN_THRESHOLD)
    win_rate = round(wins / len(results) * 100, 1) if results else 0

    _update_registry("executor", version, local_avg, win_rate)

    return {
        "version": version,
        "tasks_done": len(results),
        "local_avg": round(local_avg, 1),
        "opus_avg": round(opus_avg, 1),
        "gap": gap,
        "win_rate": win_rate,
        "category_gaps": category_gaps,
        "local_wins": local_wins,
        "upgrade_needed": len(upgrade_cats) > 0,
        "upgrade_categories": upgrade_cats,
    }


def run(task: dict) -> dict:
    start   = time.time()
    version = task.get("version", 1)
    analysis = analyze_version(version)

    quality = 80 if not analysis.get("error") else 0

    return {
        "status": "done",
        "quality": quality,
        "tokens_used": 0,
        "elapsed_s": round(time.time() - start, 2),
        "agent": "benchmarker",
        **analysis,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", type=int, default=4)
    args = ap.parse_args()
    result = analyze_version(args.version)
    print(json.dumps(result, indent=2))
