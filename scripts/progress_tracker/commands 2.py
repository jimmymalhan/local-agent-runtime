"""CLI command handlers for init, update, and show."""
from __future__ import annotations

import argparse

from .rendering import render_summary
from .state import (
    build_state,
    get_stage,
    load_state,
    now_iso,
    save_state,
    state_lock,
    update_overall,
)
from .types import ProgressState, StageState


def cmd_init(args: argparse.Namespace) -> None:
    with state_lock():
        state: ProgressState = build_state(args.task, args.stages)
        save_state(state)
    print(render_summary(state))


def cmd_update(args: argparse.Namespace, status: str) -> None:
    with state_lock():
        state: ProgressState = load_state()
        stage: StageState = get_stage(state, args.stage)
        if stage.get("status") == "completed" and status == "running":
            print(render_summary(state))
            return
        state["current_stage"] = args.stage
        if not stage["started_at"]:
            stage["started_at"] = now_iso()
        stage["status"] = status
        percent_val: float | None = args.percent
        if percent_val is not None:
            stage["percent"] = round(max(0.0, min(100.0, percent_val)), 1)
        detail_val: str | None = args.detail
        if detail_val is not None:
            stage["detail"] = detail_val
        label_val: str | None = args.label
        if label_val is not None:
            stage["label"] = label_val
        if status == "completed":
            stage["percent"] = 100.0
            stage["completed_at"] = now_iso()
            state["current_stage"] = ""
        if status == "failed":
            state["overall"]["status"] = "failed"
        update_overall(state)
        save_state(state)
    print(render_summary(state))


def cmd_show(_args: argparse.Namespace) -> None:
    with state_lock():
        state: ProgressState = load_state()
    print(render_summary(state))
    for stage in state["stages"]:
        detail: str = f" | {stage['detail']}" if stage["detail"] else ""
        print(
            f"- {stage['label']}: {stage['percent']:5.1f}% | "
            f"{stage['status']} | weight {stage['weight']:4.1f}%{detail}"
        )
