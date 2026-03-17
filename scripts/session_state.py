#!/usr/bin/env python3
import json
import os
import pathlib
from datetime import datetime


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_PATH = REPO_ROOT / "state" / "session-state.json"


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def write_state(status, task="", target_repo=""):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    default_local = 100.0 if status == "running" else 0.0
    body = {
        "status": status,
        "task": task,
        "target_repo": target_repo,
        "persona": os.environ.get("SESSION_PERSONA", "local"),
        "execution": {
            "local_models": float(os.environ.get("LOCAL_AGENT_LOCAL_PERCENT", default_local)),
            "cloud_session": float(os.environ.get("LOCAL_AGENT_CLOUD_PERCENT", "0")),
        },
        "takeover_reason": os.environ.get("LOCAL_AGENT_TAKEOVER_REASON", ""),
        "updated_at": now_iso(),
    }
    STATE_PATH.write_text(json.dumps(body, indent=2) + "\n")
    print(json.dumps(body))


if __name__ == "__main__":
    import sys
    write_state(
        status=sys.argv[1] if len(sys.argv) > 1 else "idle",
        task=sys.argv[2] if len(sys.argv) > 2 else "",
        target_repo=sys.argv[3] if len(sys.argv) > 3 else "",
    )
