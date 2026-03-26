"""Type definitions for the progress tracker."""
from __future__ import annotations

from datetime import datetime
from typing import Generic, Protocol, TypedDict, TypeVar, Union


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
        self.created_at: str = datetime.now().isoformat(timespec="seconds")

    def get(self) -> T:
        return self.value

    def __repr__(self) -> str:
        return f"StateContainer(label={self.label!r}, created_at={self.created_at!r})"
