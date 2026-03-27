#!/usr/bin/env python3
"""
ETA Calculator — Estimate when local agents will beat Opus 4.6

Based on:
1. Current win rate vs Opus 4.6
2. Historical improvement rate (if available)
3. Number of versions completed so far
4. Hours per version (1 hour = 1 version)

Assumptions if no data yet:
- Local agents start at ~40% win rate vs Opus (conservative)
- Improvement rate: +1% per version (compounding)
- Target: 100% win rate across ALL categories
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = str(Path(__file__).parent.parent)
DASHBOARD = os.path.join(BASE_DIR, "dashboard", "state.json")
REPORTS = os.path.join(BASE_DIR, "reports")


def read_state():
    """Read current state from dashboard."""
    try:
        with open(DASHBOARD) as f:
            return json.load(f)
    except:
        return {}


def read_benchmark_history():
    """Read all benchmark results to find trend."""
    results = []
    try:
        # Find all v*_compare.jsonl files
        for report_file in sorted(Path(REPORTS).glob("v*_compare.jsonl")):
            version = int(report_file.name.split("_")[0][1:])  # Extract version from "v5_compare.jsonl"
            try:
                with open(report_file) as f:
                    lines = f.readlines()
                    if lines:
                        last_result = json.loads(lines[-1])
                        win_rate = last_result.get("win_rate", last_result.get("local_win_pct", 0))
                        results.append({"version": version, "win_rate": win_rate})
            except:
                pass
    except:
        pass
    return sorted(results, key=lambda x: x["version"])


def calculate_improvement_rate(history):
    """Calculate improvement rate from historical data."""
    if len(history) < 2:
        return None

    # Average improvement per version
    improvements = []
    for i in range(1, len(history)):
        improvement = history[i]["win_rate"] - history[i-1]["win_rate"]
        improvements.append(improvement)

    avg_improvement = sum(improvements) / len(improvements) if improvements else 0
    return avg_improvement


def estimate_eta(current_version, current_win_rate, improvement_rate):
    """
    Estimate when system will reach 100% win rate.

    Args:
        current_version: Current version number (e.g., 5)
        current_win_rate: Current win rate as percentage (e.g., 45.0)
        improvement_rate: Percentage improvement per version (e.g., 1.2)

    Returns:
        dict with eta_version, eta_date, hours_remaining, confidence
    """
    if improvement_rate <= 0:
        # No improvement or declining, conservative estimate
        improvement_rate = 0.5  # Assume 0.5% per version
        confidence = "low"
    elif improvement_rate > 5:
        confidence = "high"
    else:
        confidence = "medium"

    target_win_rate = 100.0
    versions_needed = (target_win_rate - current_win_rate) / improvement_rate
    eta_version = current_version + int(versions_needed) + 1

    # Cap at v1000 (hard limit)
    if eta_version > 1000:
        eta_version = 1000

    # 1 version per hour
    hours_needed = versions_needed
    eta_datetime = datetime.now() + timedelta(hours=hours_needed)

    return {
        "eta_version": eta_version,
        "eta_date": eta_datetime.isoformat(),
        "eta_date_human": eta_datetime.strftime("%Y-%m-%d %H:%M:%S"),
        "hours_remaining": round(hours_needed, 1),
        "days_remaining": round(hours_needed / 24, 2),
        "weeks_remaining": round(hours_needed / 168, 2),
        "versions_remaining": int(versions_needed),
        "confidence": confidence,
        "improvement_rate_per_version": round(improvement_rate, 2),
    }


def main():
    state = read_state()
    history = read_benchmark_history()

    current_version = state.get("version", {}).get("current", 5)
    current_win_rate = state.get("win_rate_vs_opus", None)

    # If no data yet, use assumptions
    if current_win_rate is None:
        if history:
            current_win_rate = history[-1]["win_rate"]
        else:
            # Assume local agents start at 40% vs Opus 4.6
            current_win_rate = 40.0

    # Calculate improvement rate
    improvement_rate = calculate_improvement_rate(history)
    if improvement_rate is None:
        # Default: assume 1% improvement per version
        improvement_rate = 1.0

    # Estimate ETA
    eta = estimate_eta(current_version, current_win_rate, improvement_rate)

    # Add metadata
    eta["as_of_version"] = current_version
    eta["current_win_rate"] = current_win_rate
    eta["benchmark_history_length"] = len(history)
    eta["calculated_at"] = datetime.now().isoformat()

    # Output
    if len(sys.argv) > 1 and sys.argv[1] == "--json":
        print(json.dumps(eta, indent=2))
    else:
        print_eta_report(state, eta, history)

    # Update dashboard with ETA
    update_dashboard_eta(eta)

    return eta


def print_eta_report(state, eta, history):
    """Pretty-print ETA report."""
    print("\n" + "="*70)
    print("  ETA TO BEAT OPUS 4.6")
    print("="*70)
    print()

    print(f"Current Status:")
    print(f"  Version:              v{eta['as_of_version']} (5% complete)")
    print(f"  Win Rate vs Opus:     {eta['current_win_rate']:.1f}%")
    print(f"  Target:               100% (all categories)")
    print()

    print(f"Improvement Trend:")
    if history:
        print(f"  Historical versions:  {len(history)} versions analyzed")
        print(f"  First version:        v{history[0]['version']} ({history[0]['win_rate']:.1f}%)")
        print(f"  Latest version:       v{history[-1]['version']} ({history[-1]['win_rate']:.1f}%)")
    print(f"  Avg improvement:      +{eta['improvement_rate_per_version']:.2f}% per version")
    print(f"  Confidence:           {eta['confidence'].upper()}")
    print()

    print(f"ETA to Victory:")
    print(f"  Target version:       v{eta['eta_version']}")
    print(f"  Time remaining:       {eta['hours_remaining']} hours")
    print(f"                        {eta['days_remaining']} days")
    print(f"                        {eta['weeks_remaining']} weeks")
    print(f"  Est. completion:      {eta['eta_date_human']}")
    print()

    print(f"Notes:")
    print(f"  • ETA assumes 1 hour per version")
    print(f"  • Improvement rate estimated from {len(history)} historical runs")
    print(f"  • Actual ETA may vary based on:")
    print(f"    - Frustration research findings (every 5 versions)")
    print(f"    - Auto-upgrade effectiveness")
    print(f"    - Hardware availability")
    print()
    print("="*70 + "\n")


def update_dashboard_eta(eta):
    """Update dashboard state.json with ETA info."""
    try:
        with open(os.path.join(os.path.dirname(DASHBOARD), "state.json")) as f:
            state = json.load(f)
    except:
        state = {}

    # Add ETA section
    state["eta"] = {
        "version": eta["eta_version"],
        "date": eta["eta_date_human"],
        "hours": eta["hours_remaining"],
        "days": eta["days_remaining"],
        "weeks": eta["weeks_remaining"],
        "improvement_rate": eta["improvement_rate_per_version"],
        "confidence": eta["confidence"],
    }

    # Save
    try:
        with open(os.path.join(os.path.dirname(DASHBOARD), "state.json"), "w") as f:
            json.dump(state, f, indent=2)
    except:
        pass


if __name__ == "__main__":
    main()
