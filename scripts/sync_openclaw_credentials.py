#!/usr/bin/env python3
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from runtime_env import openclaw_status, openclaw_runtime_values, write_runtime_env


def main() -> int:
    values = openclaw_runtime_values()
    if not values:
        print(json.dumps({"status": "missing", "message": "OpenClaw local config not found or token missing."}, indent=2))
        return 1
    target = write_runtime_env(values)
    status = openclaw_status()
    status["status"] = "synced"
    status["runtime_env_path"] = str(target)
    print(json.dumps(status, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
