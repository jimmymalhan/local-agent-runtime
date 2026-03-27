"""Paths and constants for the progress tracker."""
from __future__ import annotations

import pathlib

REPO_ROOT: pathlib.Path = pathlib.Path(__file__).resolve().parents[2]
STATE_DIR: pathlib.Path = REPO_ROOT / "state"
LOG_DIR: pathlib.Path = REPO_ROOT / "logs"
PROGRESS_PATH: pathlib.Path = STATE_DIR / "progress.json"
LOG_PATH: pathlib.Path = LOG_DIR / "progress.log"
LOCK_PATH: pathlib.Path = STATE_DIR / "progress.lock"
