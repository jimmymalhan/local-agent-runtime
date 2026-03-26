"""progress_tracker — structured progress tracking with file-based state.

Public API:
    Types:  OverallState, StageState, ProgressState, StageInput, StageSpec,
            Renderable, StateContainer
    Config: REPO_ROOT, STATE_DIR, LOG_DIR, PROGRESS_PATH, LOG_PATH, LOCK_PATH
    State:  now_iso, load_state, save_state, build_state, state_lock,
            overall_percent, update_overall, get_stage
    Render: render_bar, render_summary
    CLI:    main
"""
from .cli import main
from .config import (
    LOCK_PATH,
    LOG_DIR,
    LOG_PATH,
    PROGRESS_PATH,
    REPO_ROOT,
    STATE_DIR,
)
from .rendering import render_bar, render_summary
from .state import (
    build_state,
    get_stage,
    load_state,
    now_iso,
    overall_percent,
    save_state,
    state_lock,
    update_overall,
)
from .types import (
    OverallState,
    ProgressState,
    Renderable,
    StageInput,
    StageSpec,
    StageState,
    StateContainer,
)

__all__ = [
    "LOCK_PATH",
    "LOG_DIR",
    "LOG_PATH",
    "PROGRESS_PATH",
    "REPO_ROOT",
    "STATE_DIR",
    "OverallState",
    "ProgressState",
    "Renderable",
    "StageInput",
    "StageSpec",
    "StageState",
    "StateContainer",
    "build_state",
    "get_stage",
    "load_state",
    "main",
    "now_iso",
    "overall_percent",
    "render_bar",
    "render_summary",
    "save_state",
    "state_lock",
    "update_overall",
]
