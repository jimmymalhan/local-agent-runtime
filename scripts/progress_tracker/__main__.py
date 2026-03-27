"""Entry point for `python -m progress_tracker`.

When run with CLI args, delegates to the CLI. Otherwise runs self-test assertions.
"""
from __future__ import annotations

import sys

from .rendering import render_bar, render_summary
from .state import build_state, get_stage, now_iso, overall_percent, update_overall
from .types import (
    OverallState,
    ProgressState,
    StageInput,
    StageState,
    StateContainer,
)


def _run_self_tests() -> None:
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

    # 11. Test no circular imports — all public names importable
    from . import __all__ as exported_names  # noqa: F811

    assert "main" in exported_names
    assert "build_state" in exported_names
    assert "render_bar" in exported_names
    assert "ProgressState" in exported_names

    print("All assertions passed.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        from .cli import main

        main()
    else:
        _run_self_tests()
