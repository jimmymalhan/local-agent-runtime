#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from todo_progress import parse_todo


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_PATH = REPO_ROOT / "state" / "roi-metrics.json"
LEDGER_PATH = REPO_ROOT / "state" / "ledger.md"
RUNTIME_PATH = REPO_ROOT / "config" / "runtime.json"


def recent_cost_average(limit: int = 6) -> float:
    if not LEDGER_PATH.exists():
        return 0.0
    costs = []
    for line in LEDGER_PATH.read_text(errors="ignore").splitlines():
        if not line.startswith("|"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 8 or parts[1] == "Timestamp":
            continue
        try:
            costs.append(float(parts[7]))
        except ValueError:
            continue
    if not costs:
        return 0.0
    window = costs[-limit:]
    return round(sum(window) / len(window), 6)


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"events": []}
    try:
        data = json.loads(STATE_PATH.read_text())
    except json.JSONDecodeError:
        return {"events": []}
    data["events"] = prune_events(data.get("events", []))
    negatives = sum(1 for item in data["events"] if item.get("outcome") == "negative")
    positives = sum(1 for item in data["events"] if item.get("outcome") == "positive")
    threshold = roi_threshold()
    data["trend"] = "negative" if negatives >= threshold and negatives > positives else "healthy"
    data["kill_switch"] = data["trend"] == "negative"
    return data


def runtime_config() -> dict:
    try:
        return json.loads(RUNTIME_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def roi_max_age_minutes() -> int:
    return int(runtime_config().get("roi", {}).get("max_event_age_minutes", 15))


def roi_threshold() -> int:
    return int(runtime_config().get("roi", {}).get("negative_trend_threshold", 3))


def prune_events(events: list[dict]) -> list[dict]:
    cutoff = datetime.now() - timedelta(minutes=roi_max_age_minutes())
    kept = []
    for item in events:
        stamp = item.get("timestamp", "")
        try:
            when = datetime.fromisoformat(stamp)
        except ValueError:
            kept.append(item)
            continue
        if when >= cutoff:
            kept.append(item)
    return kept


def current_snapshot() -> dict:
    todo = parse_todo()
    overall = todo["overall"]
    return {
        "open": overall["open"],
        "done": overall["done"],
        "percent": overall["percent"],
        "avg_cost": recent_cost_average(),
    }


def classify_negative(previous: dict, current: dict, status: str) -> bool:
    no_progress = current["open"] >= previous.get("open", current["open"]) and current["percent"] <= previous.get("percent", current["percent"])
    cost_up = current["avg_cost"] > previous.get("avg_cost", 0.0)
    failed = status != "success"
    return (failed or no_progress) and cost_up


def cmd_check(max_negative_runs: int) -> int:
    state = load_state()
    if not state.get("events"):
        print("ROI guard: no prior baseline, allow run.")
        return 0
    if state.get("kill_switch") or int(state.get("consecutive_negative", 0)) >= max_negative_runs:
        print("ROI kill switch: negative ROI trend persisted across recent runs. Stop and re-plan before scaling.")
        return 2
    print("ROI guard: allow run.")
    return 0


def cmd_record(status: str, max_negative_runs: int) -> int:
    current = current_snapshot()
    previous = load_state()
    outcome = "negative" if classify_negative(previous, current, status) else "positive"
    events = list(previous.get("events", []))
    events.append(
        {
            "timestamp": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "stage": "pipeline",
            "outcome": outcome,
            "detail": f"status={status} open={current['open']} percent={current['percent']} avg_cost={current['avg_cost']}",
        }
    )
    events = events[-max(1, max_negative_runs * 2):]
    consecutive = 0
    for item in reversed(events):
        if item.get("outcome") != "negative":
            break
        consecutive += 1
    body = {
        "events": events,
        "trend": "negative" if consecutive >= max_negative_runs else "healthy",
        "kill_switch": consecutive >= max_negative_runs,
        "consecutive_negative": consecutive,
        "kill_switch_threshold": max_negative_runs,
        **current,
        "status": status,
    }
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(body, indent=2) + "\n")
    print(json.dumps(body))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-negative-runs", type=int, default=2)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    record = sub.add_parser("record")
    record.add_argument("--status", default="success")
    args = parser.parse_args()
    if args.cmd == "check":
        return cmd_check(args.max_negative_runs)
    return cmd_record(args.status, args.max_negative_runs)


if __name__ == "__main__":
    raise SystemExit(main())
