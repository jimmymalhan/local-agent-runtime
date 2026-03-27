"""State management: load, save, build, lock, and query operations."""
from __future__ import annotations

import fcntl
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Generator, Sequence

from .config import LOCK_PATH, LOG_DIR, LOG_PATH, PROGRESS_PATH, STATE_DIR
from .types import OverallState, ProgressState, StageInput, StageSpec, StageState


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_state() -> ProgressState:
    if not PROGRESS_PATH.exists():
        raise SystemExit("No progress state available.")
    data: ProgressState = json.loads(PROGRESS_PATH.read_text())
    return data


@contextmanager
def state_lock() -> Generator[None, None, None]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def save_state(state: ProgressState) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = now_iso()
    PROGRESS_PATH.write_text(json.dumps(state, indent=2) + "\n")
    LOG_PATH.open("a").write(
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} progress "
        f"{state['overall']['percent']:.1f}% {state['task']}\n"
    )


def build_state(task: str, stages: Sequence[StageSpec]) -> ProgressState:
    stage_list: list[StageState] = []
    for stage in stages:
        if isinstance(stage, dict):
            stage_list.append(
                StageState(
                    id=stage["id"],
                    label=stage["label"],
                    weight=float(stage.get("weight", 0.0)),
                    percent=0.0,
                    status="pending",
                    detail="",
                    started_at="",
                    completed_at="",
                )
            )
        else:
            stage_list.append(
                StageState(
                    id=stage,
                    label=stage.replace("-", " "),
                    weight=0.0,
                    percent=0.0,
                    status="pending",
                    detail="",
                    started_at="",
                    completed_at="",
                )
            )
    return ProgressState(
        task=task,
        started_at=now_iso(),
        updated_at=now_iso(),
        overall=OverallState(
            percent=0.0,
            remaining_percent=100.0,
            status="running",
        ),
        current_stage="",
        stages=stage_list,
    )


def overall_percent(state: ProgressState) -> float:
    total_weight: float = sum(stage["weight"] for stage in state["stages"]) or 1.0
    completed: float = sum(
        stage["weight"] * stage["percent"] / 100.0 for stage in state["stages"]
    )
    return round(max(0.0, min(100.0, completed / total_weight * 100.0)), 1)


def update_overall(state: ProgressState) -> ProgressState:
    state["overall"]["percent"] = overall_percent(state)
    state["overall"]["remaining_percent"] = round(
        100.0 - state["overall"]["percent"], 1
    )
    if all(stage["status"] == "completed" for stage in state["stages"]):
        state["overall"]["status"] = "completed"
    return state


def get_stage(state: ProgressState, stage_id: str) -> StageState:
    for stage in state["stages"]:
        if stage["id"] == stage_id:
            return stage
    raise SystemExit(f"Unknown stage: {stage_id}")
