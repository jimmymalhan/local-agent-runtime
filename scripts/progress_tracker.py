#!/usr/bin/env python3
"""Thin wrapper — delegates to the progress_tracker package.

Backward-compatible entry point: `python scripts/progress_tracker.py <cmd>`.
All logic lives in scripts/progress_tracker/ now.
"""
from __future__ import annotations

import sys

# Re-export full public API so existing `from progress_tracker import X` still works
from progress_tracker import (  # noqa: F401
    LOCK_PATH,
    LOG_DIR,
    LOG_PATH,
    PROGRESS_PATH,
    REPO_ROOT,
    STATE_DIR,
    OverallState,
    ProgressState,
    Renderable,
    StageInput,
    StageSpec,
    StageState,
    StateContainer,
    build_state,
    get_stage,
    load_state,
    main,
    now_iso,
    overall_percent,
    render_bar,
    render_summary,
    save_state,
    state_lock,
    update_overall,
)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        main()
    else:
        # Run self-tests via the package's __main__
        from progress_tracker.__main__ import _run_self_tests

        _run_self_tests()
