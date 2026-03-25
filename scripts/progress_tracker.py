#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import pathlib
from contextlib import contextmanager
from datetime import datetime
from typing import (
    Any,
    Generator,
    Generic,
    Iterator,
    Protocol,
    Sequence,
    TypedDict,
    TypeVar,
    Union,
)

# ---------------------------------------------------------------------------
# Type definitions
# ---------------------------------------------------------------------------


class OverallState(TypedDict):
    percent: float
    remaining_percent: float
    status: str


class StageState(TypedDict):
    id: str
    label: str
    weight: float
    percent: float
    status: str
    detail: str
    started_at: str
    completed_at: str


class ProgressState(TypedDict):
    task: str
    started_at: str
    updated_at: str
    overall: OverallState
    current_stage: str
    stages: list[StageState]


class StageInput(TypedDict):
    id: str
    weight: float
    label: str


StageSpec = Union[StageInput, str]

T = TypeVar("T")


class Renderable(Protocol):
    """Protocol for objects that can produce a text summary."""

    def render(self) -> str: ...


class StateContainer(Generic[T]):
    """Generic container wrapping a state value with metadata."""

    def __init__(self, value: T, label: str = "") -> None:
        self.value: T = value
        self.label: str = label
        self.created_at: str = now_iso()

    def get(self) -> T:
        return self.value

    def __repr__(self) -> str:
        return f"StateContainer(label={self.label!r}, created_at={self.created_at!r})"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT: pathlib.Path = pathlib.Path(__file__).resolve().parents[1]
STATE_DIR: pathlib.Path = REPO_ROOT / "state"
LOG_DIR: pathlib.Path = REPO_ROOT / "logs"
PROGRESS_PATH: pathlib.Path = STATE_DIR / "progress.json"
LOG_PATH: pathlib.Path = LOG_DIR / "progress.log"
LOCK_PATH: pathlib.Path = STATE_DIR / "progress.lock"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def render_bar(percent: float, width: int = 24) -> str:
    filled: int = round(width * max(0.0, min(100.0, percent)) / 100.0)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


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


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


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


def render_summary(state: ProgressState) -> str:
    lines: list[str] = [
        f"OVERALL {render_bar(state['overall']['percent'])} "
        f"{state['overall']['percent']:5.1f}% | "
        f"remaining {state['overall']['remaining_percent']:5.1f}% | "
        f"{state['task']}"
    ]
    current_id: str = state.get("current_stage", "")
    if current_id:
        current: StageState = get_stage(state, current_id)
        suffix: str = f" | {current['detail']}" if current["detail"] else ""
        lines.append(
            f"STAGE   {render_bar(current['percent'])} "
            f"{current['percent']:5.1f}% | {current['label']}{suffix}"
        )
    return "\n".join(lines)


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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    sub: argparse._SubParsersAction[argparse.ArgumentParser] = (
        parser.add_subparsers(dest="cmd", required=True)
    )

    init: argparse.ArgumentParser = sub.add_parser("init")
    init.add_argument("--task", required=True)
    init.add_argument("--stages", nargs="+", required=True)
    init.add_argument("--weights", nargs="*")
    init.add_argument("--labels", nargs="*")

    for name in ("start", "tick", "complete", "fail"):
        p: argparse.ArgumentParser = sub.add_parser(name)
        p.add_argument("--stage", required=True)
        p.add_argument("--label")
        p.add_argument("--percent", type=float)
        p.add_argument("--detail")

    sub.add_parser("show")

    args: argparse.Namespace = parser.parse_args()
    if args.cmd == "init":
        weights_list: list[str] | None = args.weights
        if weights_list:
            if len(weights_list) != len(args.stages):
                raise SystemExit("weights length must match stages length")
            labels_list: list[str] = args.labels or args.stages
            if len(labels_list) != len(args.stages):
                raise SystemExit("labels length must match stages length")
            args.stages = [
                StageInput(id=stage_id, weight=float(weight), label=label)
                for stage_id, weight, label in zip(
                    args.stages, weights_list, labels_list
                )
            ]
        else:
            total: int = len(args.stages) or 1
            weight: float = round(100.0 / total, 2)
            args.stages = [
                StageInput(
                    id=stage_id,
                    weight=weight,
                    label=stage_id.replace("-", " "),
                )
                for stage_id in args.stages
            ]
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


# ---------------------------------------------------------------------------
# Self-test + entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        main()
    else:
        # ---- Self-test assertions ----

        # 1. Test now_iso returns ISO format string
        ts: str = now_iso()
        assert isinstance(ts, str), f"now_iso should return str, got {type(ts)}"
        assert "T" in ts, f"ISO timestamp should contain 'T': {ts}"

        # 2. Test render_bar
        bar_0: str = render_bar(0.0)
        assert bar_0 == "[" + "-" * 24 + "]", f"0% bar wrong: {bar_0}"
        bar_100: str = render_bar(100.0)
        assert bar_100 == "[" + "#" * 24 + "]", f"100% bar wrong: {bar_100}"
        bar_50: str = render_bar(50.0)
        assert bar_50.startswith("[") and bar_50.endswith("]")
        assert "#" in bar_50 and "-" in bar_50
        # Clamp beyond 100
        bar_over: str = render_bar(150.0)
        assert bar_over == "[" + "#" * 24 + "]", f"Overclamped bar wrong: {bar_over}"
        # Custom width
        bar_w8: str = render_bar(50.0, width=8)
        assert len(bar_w8) == 10, f"Width-8 bar length wrong: {len(bar_w8)}"

        # 3. Test build_state with string specs
        state_str: ProgressState = build_state("test-task", ["stage-a", "stage-b"])
        assert state_str["task"] == "test-task"
        assert len(state_str["stages"]) == 2
        assert state_str["stages"][0]["id"] == "stage-a"
        assert state_str["stages"][0]["label"] == "stage a"
        assert state_str["stages"][0]["percent"] == 0.0
        assert state_str["stages"][0]["status"] == "pending"
        assert state_str["overall"]["percent"] == 0.0
        assert state_str["overall"]["remaining_percent"] == 100.0
        assert state_str["overall"]["status"] == "running"

        # 4. Test build_state with dict specs (StageInput)
        inputs: list[StageInput] = [
            StageInput(id="s1", weight=60.0, label="First"),
            StageInput(id="s2", weight=40.0, label="Second"),
        ]
        state_dict: ProgressState = build_state("dict-task", inputs)
        assert state_dict["stages"][0]["weight"] == 60.0
        assert state_dict["stages"][1]["label"] == "Second"

        # 5. Test overall_percent
        assert overall_percent(state_str) == 0.0
        # Simulate completion of one stage in equal-weight scenario
        state_dict["stages"][0]["percent"] = 100.0
        state_dict["stages"][0]["weight"] = 50.0
        state_dict["stages"][1]["percent"] = 0.0
        state_dict["stages"][1]["weight"] = 50.0
        assert overall_percent(state_dict) == 50.0

        # Full completion
        state_dict["stages"][1]["percent"] = 100.0
        assert overall_percent(state_dict) == 100.0

        # 6. Test update_overall
        state_upd: ProgressState = build_state("upd-task", ["a", "b"])
        state_upd["stages"][0]["weight"] = 50.0
        state_upd["stages"][1]["weight"] = 50.0
        state_upd["stages"][0]["percent"] = 50.0
        state_upd = update_overall(state_upd)
        assert state_upd["overall"]["percent"] == 25.0
        assert state_upd["overall"]["remaining_percent"] == 75.0
        assert state_upd["overall"]["status"] == "running"

        # Mark both completed
        state_upd["stages"][0]["percent"] = 100.0
        state_upd["stages"][0]["status"] = "completed"
        state_upd["stages"][1]["percent"] = 100.0
        state_upd["stages"][1]["status"] = "completed"
        state_upd = update_overall(state_upd)
        assert state_upd["overall"]["status"] == "completed"
        assert state_upd["overall"]["percent"] == 100.0

        # 7. Test get_stage
        found: StageState = get_stage(state_upd, "a")
        assert found["id"] == "a"
        try:
            get_stage(state_upd, "nonexistent")
            assert False, "Should have raised SystemExit"
        except SystemExit:
            pass

        # 8. Test render_summary
        summary: str = render_summary(state_upd)
        assert "OVERALL" in summary
        assert "upd-task" in summary

        # With a current stage set
        state_upd["current_stage"] = "a"
        summary_with_stage: str = render_summary(state_upd)
        assert "STAGE" in summary_with_stage

        # 9. Test StateContainer (Generic usage)
        container_int: StateContainer[int] = StateContainer(42, label="answer")
        assert container_int.get() == 42
        assert container_int.label == "answer"
        assert "StateContainer" in repr(container_int)

        container_str: StateContainer[str] = StateContainer("hello")
        assert container_str.get() == "hello"

        container_list: StateContainer[list[float]] = StateContainer(
            [1.0, 2.0, 3.0], label="scores"
        )
        assert len(container_list.get()) == 3

        # 10. Test OverallState / StageState as TypedDicts
        overall: OverallState = OverallState(
            percent=50.0, remaining_percent=50.0, status="running"
        )
        assert overall["percent"] == 50.0
        stage: StageState = StageState(
            id="x",
            label="X",
            weight=10.0,
            percent=0.0,
            status="pending",
            detail="",
            started_at="",
            completed_at="",
        )
        assert stage["id"] == "x"

        print("All assertions passed.")
