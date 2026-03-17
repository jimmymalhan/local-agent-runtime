#!/usr/bin/env python3
import argparse
import json
import os
import pathlib
import signal
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_ROOT / "logs" / "session-health-report.md"


@dataclass
class SessionProcess:
    pid: int
    ppid: int
    tty: str
    stat: str
    started_at: datetime
    command: str
    tool: str

    @property
    def is_stopped(self) -> bool:
        return "T" in self.stat

    @property
    def is_active(self) -> bool:
        return not self.is_stopped


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def detect_tool(command: str) -> str | None:
    lowered = command.lower()
    if "/bin/codex" in lowered or lowered.startswith("codex ") or lowered == "codex":
        return "codex"
    if "/bin/claude" in lowered or lowered.startswith("claude ") or lowered == "claude":
        return "claude"
    return None


def parse_process_table(ps_output: str):
    sessions = []
    for raw in ps_output.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        parts = line.split(None, 9)
        if len(parts) < 10:
            continue
        pid, ppid, tty, stat = int(parts[0]), int(parts[1]), parts[2], parts[3]
        started_at = datetime.strptime(" ".join(parts[4:9]), "%a %b %d %H:%M:%S %Y")
        command = parts[9]
        tool = detect_tool(command)
        if not tool:
            continue
        sessions.append(
            SessionProcess(
                pid=pid,
                ppid=ppid,
                tty=tty,
                stat=stat,
                started_at=started_at,
                command=command,
                tool=tool,
            )
        )
    return sessions


def load_sessions():
    result = run(["ps", "-Ao", "pid,ppid,tty,stat,lstart,command"])
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "ps failed")
    return parse_process_table(result.stdout)


def analyze_sessions(sessions):
    by_key = {}
    for session in sessions:
        by_key.setdefault((session.tool, session.tty), []).append(session)

    stale_duplicates = []
    for key, group in by_key.items():
        active = sorted([item for item in group if item.is_active], key=lambda item: (item.started_at, item.pid))
        if len(active) <= 1:
            continue
        keep = active[-1]
        for item in active[:-1]:
            stale_duplicates.append(
                {
                    "tool": key[0],
                    "tty": key[1],
                    "pid": item.pid,
                    "keep_pid": keep.pid,
                    "started_at": item.started_at.isoformat(timespec="seconds"),
                    "keep_started_at": keep.started_at.isoformat(timespec="seconds"),
                    "command": item.command,
                }
            )
    stale_duplicates.sort(key=lambda item: (item["tool"], item["tty"], item["pid"]))
    return stale_duplicates


def suspend_duplicates(duplicates):
    actions = []
    warnings = []
    for item in duplicates:
        try:
            os.kill(item["pid"], signal.SIGSTOP)
            actions.append(f"Suspended stale {item['tool']} session pid {item['pid']} on {item['tty']} (keeping pid {item['keep_pid']}).")
        except OSError as exc:
            warnings.append(f"Failed to suspend pid {item['pid']} on {item['tty']}: {exc}")
    return actions, warnings


def render_report(sessions, duplicates, heal_actions, warnings):
    lines = [
        "# Session Health Report",
        "",
        f"- generated_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- detected_sessions: {len(sessions)}",
        f"- duplicate_active_sessions: {len(duplicates)}",
        "",
        "## Active Sessions",
    ]
    active_sessions = [item for item in sessions if item.is_active]
    if active_sessions:
        for item in sorted(active_sessions, key=lambda item: (item.tool, item.tty, item.started_at, item.pid)):
            lines.append(
                f"- {item.tool} pid {item.pid} on {item.tty} started {item.started_at.isoformat(timespec='seconds')} :: {item.command}"
            )
    else:
        lines.append("- none")
    lines.extend(["", "## Duplicate Active Sessions"])
    if duplicates:
        for item in duplicates:
            lines.append(
                f"- {item['tool']} on {item['tty']}: stale pid {item['pid']} should yield to pid {item['keep_pid']}"
            )
    else:
        lines.append("- none")
    lines.extend(["", "## Heal Actions"])
    if heal_actions:
        lines.extend(f"- {item}" for item in heal_actions)
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings"])
    if warnings:
        lines.extend(f"- {item}" for item in warnings)
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--heal", action="store_true", help="Suspend duplicate active Codex/Claude sessions on the same TTY.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of markdown.")
    args = parser.parse_args()

    sessions = load_sessions()
    duplicates = analyze_sessions(sessions)
    heal_actions = []
    warnings = []
    if args.heal and duplicates:
        heal_actions, warnings = suspend_duplicates(duplicates)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = render_report(sessions, duplicates, heal_actions, warnings)
    REPORT_PATH.write_text(report)

    payload = {
        "sessions": [
            {
                "pid": item.pid,
                "ppid": item.ppid,
                "tty": item.tty,
                "stat": item.stat,
                "started_at": item.started_at.isoformat(timespec="seconds"),
                "command": item.command,
                "tool": item.tool,
            }
            for item in sessions
        ],
        "duplicates": duplicates,
        "heal_actions": heal_actions,
        "warnings": warnings,
        "report_path": str(REPORT_PATH),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(report)
    raise SystemExit(0 if not warnings else 1)


if __name__ == "__main__":
    main()
