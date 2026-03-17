#!/usr/bin/env python3
import json
import os
import pathlib
import platform
import subprocess
from datetime import datetime


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_PATH = REPO_ROOT / "state" / "resource-status.json"
RUNTIME_JSON = REPO_ROOT / "config" / "runtime.json"
RUNTIME_ENV = REPO_ROOT / "state" / "runtime.env"


def threshold_percent():
    if RUNTIME_ENV.exists():
        for line in RUNTIME_ENV.read_text().splitlines():
            if line.startswith("LOCAL_AGENT_MAX_CPU_PERCENT="):
                try:
                    return int(line.split("=", 1)[1].strip())
                except ValueError:
                    break
    if RUNTIME_JSON.exists():
        return int(json.loads(RUNTIME_JSON.read_text()).get("resource_limits", {}).get("cpu_percent", 70))
    return 70


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def cpu_count():
    return max(1, os.cpu_count() or 1)


def cpu_percent():
    system = platform.system()
    if system == "Darwin":
        result = run(["ps", "-A", "-o", "%cpu="]).stdout.splitlines()
        total = 0.0
        for line in result:
            try:
                total += float(line.strip() or 0)
            except ValueError:
                continue
        return round(min(100.0, total / cpu_count()), 1)
    result = run(["ps", "-A", "-o", "%cpu="]).stdout.splitlines()
    total = 0.0
    for line in result:
        try:
            total += float(line.strip() or 0)
        except ValueError:
            continue
    return round(min(100.0, total / cpu_count()), 1)


def memory_percent():
    system = platform.system()
    if system == "Darwin":
        output = run(["memory_pressure"]).stdout
        for line in output.splitlines():
            if "System-wide memory free percentage:" in line:
                free = float(line.split(":")[-1].strip().rstrip("%"))
                return round(100.0 - free, 1)
        return 0.0
    line = run(["free", "-m"]).stdout.splitlines()
    for row in line:
        if not row.startswith("Mem:"):
            continue
        parts = row.split()
        total = int(parts[1])
        used = int(parts[2])
        return round(used * 100.0 / total, 1) if total else 0.0
    return 0.0


def main():
    state = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "cpu_percent": cpu_percent(),
        "memory_percent": memory_percent(),
        "threshold_percent": threshold_percent(),
    }
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")
    print(
        f"RESOURCE cpu={state['cpu_percent']:4.1f}%/{state['threshold_percent']}% mem={state['memory_percent']:4.1f}%/{state['threshold_percent']}%"
    )


if __name__ == "__main__":
    main()
