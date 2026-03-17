#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import os
import pathlib
import subprocess
import time
from datetime import datetime


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
LOG_DIR = REPO_ROOT / "logs"
STATE_DIR = REPO_ROOT / "state"
PERSONAS = {
    "codex": REPO_ROOT / "scripts" / "start_codex_compatible.sh",
    "claude": REPO_ROOT / "scripts" / "start_claude_compatible.sh",
}


def run_persona(persona: str, script_path: pathlib.Path, task: str, target_repo: pathlib.Path, mode: str) -> dict:
    env = dict(os.environ)
    env["LOCAL_AGENT_TARGET_REPO"] = str(target_repo)
    env["LOCAL_AGENT_MODE"] = mode
    env["LOCAL_AGENT_AUTO_REVIEW"] = env.get("LOCAL_AGENT_AUTO_REVIEW", "1")
    started = time.monotonic()
    proc = subprocess.run(
        ["bash", str(script_path), str(target_repo), task],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return {
        "persona": persona,
        "returncode": proc.returncode,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def diff_excerpt(left: str, right: str, limit: int = 120) -> str:
    diff = list(
        difflib.unified_diff(
            left.splitlines(),
            right.splitlines(),
            fromfile="codex",
            tofile="claude",
            lineterm="",
        )
    )
    if not diff:
        return "No textual diff. Outputs matched exactly."
    return "\n".join(diff[:limit])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", help="Task to run in both local personas.")
    parser.add_argument("target_repo", nargs="?", default=".", help="Target repo for the task.")
    parser.add_argument("--mode", default=os.environ.get("LOCAL_AGENT_MODE", "fast"))
    args = parser.parse_args()

    target_repo = pathlib.Path(args.target_repo).resolve()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = LOG_DIR / f"session-compare-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for persona, script_path in PERSONAS.items():
        result = run_persona(persona, script_path, args.task, target_repo, args.mode)
        results.append(result)
        (out_dir / f"{persona}.stdout.md").write_text(result["stdout"])
        (out_dir / f"{persona}.stderr.log").write_text(result["stderr"])

    summary = {
        "task": args.task,
        "target_repo": str(target_repo),
        "mode": args.mode,
        "timestamp": stamp,
        "results": [
            {
                "persona": item["persona"],
                "returncode": item["returncode"],
                "elapsed_seconds": item["elapsed_seconds"],
            }
            for item in results
        ],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    diff_body = diff_excerpt(results[0]["stdout"], results[1]["stdout"])
    markdown = [
        "# Session Compare",
        "",
        f"- task: `{args.task}`",
        f"- target_repo: `{target_repo}`",
        f"- mode: `{args.mode}`",
        "",
    ]
    for item in results:
        markdown.extend(
            [
                f"## {item['persona']}",
                f"- returncode: `{item['returncode']}`",
                f"- elapsed_seconds: `{item['elapsed_seconds']}`",
                f"- stdout: `{out_dir / (item['persona'] + '.stdout.md')}`",
                f"- stderr: `{out_dir / (item['persona'] + '.stderr.log')}`",
                "",
            ]
        )
    markdown.extend(["## Diff excerpt", "", "```diff", diff_body, "```", ""])
    report_path = out_dir / "report.md"
    report_path.write_text("\n".join(markdown))
    (STATE_DIR / "session-compare-last.md").write_text(report_path.read_text())

    print(report_path)
    return 0 if all(item["returncode"] == 0 for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
