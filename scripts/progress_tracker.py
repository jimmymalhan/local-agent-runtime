#!/usr/bin/env python3
import argparse
import fcntl
import json
import pathlib
from datetime import datetime
from contextlib import contextmanager


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_DIR = REPO_ROOT / "state"
LOG_DIR = REPO_ROOT / "logs"
PROGRESS_PATH = STATE_DIR / "progress.json"
LOG_PATH = LOG_DIR / "progress.log"
LOCK_PATH = STATE_DIR / "progress.lock"


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def load_state():
    if not PROGRESS_PATH.exists():
        raise SystemExit("No progress state available.")
    return json.loads(PROGRESS_PATH.read_text())


@contextmanager
def state_lock():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def save_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = now_iso()
    PROGRESS_PATH.write_text(json.dumps(state, indent=2) + "\n")
    LOG_PATH.open("a").write(
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} progress {state['overall']['percent']:.1f}% {state['task']}\n"
    )


def build_state(task, stages):
    return {
        "task": task,
        "started_at": now_iso(),
        "updated_at": now_iso(),
        "overall": {
            "percent": 0.0,
            "remaining_percent": 100.0,
            "status": "running",
        },
        "current_stage": "",
        "stages": [
            {
                "id": stage["id"] if isinstance(stage, dict) else stage,
                "label": stage["label"] if isinstance(stage, dict) else stage.replace("-", " "),
                "weight": float(stage.get("weight", 0.0) if isinstance(stage, dict) else 0.0),
                "percent": 0.0,
                "status": "pending",
                "detail": "",
                "started_at": "",
                "completed_at": "",
            }
            for stage in stages
        ],
    }


def overall_percent(state):
    total_weight = sum(stage["weight"] for stage in state["stages"]) or 1.0
    completed = sum(stage["weight"] * stage["percent"] / 100.0 for stage in state["stages"])
    return round(max(0.0, min(100.0, completed / total_weight * 100.0)), 1)


def render_bar(percent, width=24):
    filled = round(width * max(0.0, min(100.0, percent)) / 100.0)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def update_overall(state):
    state["overall"]["percent"] = overall_percent(state)
    state["overall"]["remaining_percent"] = round(100.0 - state["overall"]["percent"], 1)
    if all(stage["status"] == "completed" for stage in state["stages"]):
        state["overall"]["status"] = "completed"
    return state


def get_stage(state, stage_id):
    for stage in state["stages"]:
        if stage["id"] == stage_id:
            return stage
    raise SystemExit(f"Unknown stage: {stage_id}")


def cmd_init(args):
    with state_lock():
        state = build_state(args.task, args.stages)
        save_state(state)
    print(render_summary(state))


def cmd_update(args, status):
    with state_lock():
        state = load_state()
        stage = get_stage(state, args.stage)
        if stage.get("status") == "completed" and status == "running":
            print(render_summary(state))
            return
        state["current_stage"] = args.stage
        if not stage["started_at"]:
            stage["started_at"] = now_iso()
        stage["status"] = status
        if args.percent is not None:
            stage["percent"] = round(max(0.0, min(100.0, args.percent)), 1)
        if args.detail is not None:
            stage["detail"] = args.detail
        if args.label is not None:
            stage["label"] = args.label
        if status == "completed":
            stage["percent"] = 100.0
            stage["completed_at"] = now_iso()
            state["current_stage"] = ""
        if status == "failed":
            state["overall"]["status"] = "failed"
        update_overall(state)
        save_state(state)
    print(render_summary(state))


def render_summary(state):
    lines = [
        f"OVERALL {render_bar(state['overall']['percent'])} {state['overall']['percent']:5.1f}% | remaining {state['overall']['remaining_percent']:5.1f}% | {state['task']}"
    ]
    current_id = state.get("current_stage", "")
    if current_id:
        current = get_stage(state, current_id)
        suffix = f" | {current['detail']}" if current["detail"] else ""
        lines.append(
            f"STAGE   {render_bar(current['percent'])} {current['percent']:5.1f}% | {current['label']}{suffix}"
        )
    return "\n".join(lines)


def cmd_show(_args):
    with state_lock():
        state = load_state()
    print(render_summary(state))
    for stage in state["stages"]:
        detail = f" | {stage['detail']}" if stage["detail"] else ""
        print(f"- {stage['label']}: {stage['percent']:5.1f}% | {stage['status']} | weight {stage['weight']:4.1f}%{detail}")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    init = sub.add_parser("init")
    init.add_argument("--task", required=True)
    init.add_argument("--stages", nargs="+", required=True)
    init.add_argument("--weights", nargs="*")
    init.add_argument("--labels", nargs="*")

    for name in ("start", "tick", "complete", "fail"):
        p = sub.add_parser(name)
        p.add_argument("--stage", required=True)
        p.add_argument("--label")
        p.add_argument("--percent", type=float)
        p.add_argument("--detail")

    sub.add_parser("show")

    args = parser.parse_args()
    if args.cmd == "init":
        if args.weights:
            if len(args.weights) != len(args.stages):
                raise SystemExit("weights length must match stages length")
            labels = args.labels or args.stages
            if len(labels) != len(args.stages):
                raise SystemExit("labels length must match stages length")
            args.stages = [
                {"id": stage_id, "weight": float(weight), "label": label}
                for stage_id, weight, label in zip(args.stages, args.weights, labels)
            ]
        else:
            total = len(args.stages) or 1
            weight = round(100.0 / total, 2)
            args.stages = [{"id": stage_id, "weight": weight, "label": stage_id.replace("-", " ")} for stage_id in args.stages]
        cmd_init(args)
    elif args.cmd == "show":
        cmd_show(args)
    elif args.cmd == "start":
        cmd_update(args, "running")
    elif args.cmd == "tick":
        cmd_update(args, "running")
    elif args.cmd == "complete":
        cmd_update(args, "completed")
    else:
        cmd_update(args, "failed")


if __name__ == "__main__":
    main()
