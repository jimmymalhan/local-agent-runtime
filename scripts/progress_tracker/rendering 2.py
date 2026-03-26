"""Rendering utilities for progress bars and summaries."""
from __future__ import annotations

from .state import get_stage
from .types import ProgressState, StageState


def render_bar(percent: float, width: int = 24) -> str:
    filled: int = round(width * max(0.0, min(100.0, percent)) / 100.0)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


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
