#!/usr/bin/env python3
"""
MCP server that routes tasks to the local agent runtime (Ollama).
Use this only when the user explicitly asks for the local runtime instead of Codex, Claude, or Cursor execution.
"""
from __future__ import annotations

import pathlib
import subprocess

from mcp.server.fastmcp import FastMCP

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN_PIPELINE = REPO_ROOT / "scripts" / "run_pipeline.sh"

mcp = FastMCP(
    "local-runtime",
    description="Runs tasks through the local agent pipeline (Ollama). Use only when the user explicitly asks for local agent, Local, local-codex, or Ollama. Do NOT use when the user asks to open Codex, Claude, or Cursor—those run independently.",
)


@mcp.tool()
def run_local_pipeline(task: str, target_repo: str = "", mode: str = "exhaustive") -> str:
    """Run a task through the local agent pipeline (Ollama). Use ONLY when the user explicitly asks for local agent, Local, local-codex, or Ollama. Do NOT call when the user asks to open Codex, Claude, or Cursor—help them open those instead."""
    if not RUN_PIPELINE.exists():
        return f"Error: run_pipeline.sh not found at {RUN_PIPELINE}"
    repo = target_repo.strip() or __import__("os").environ.get("LOCAL_AGENT_TARGET_REPO", str(REPO_ROOT))
    requested_mode = mode.strip() or "exhaustive"
    try:
        result = subprocess.run(
            [str(RUN_PIPELINE), task],
            capture_output=True,
            text=True,
            timeout=3600,
            cwd=str(REPO_ROOT),
            env={
                **__import__("os").environ,
                "LOCAL_AGENT_TARGET_REPO": repo,
                "LOCAL_AGENT_MODE": requested_mode,
                "LOCAL_AGENT_AUTO_REVIEW": "1",
            },
        )
        out = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            out = f"[Pipeline exit code: {result.returncode}]\n{out}"
        return out or "Pipeline completed (no output)."
    except subprocess.TimeoutExpired:
        return "Pipeline timed out after 3600s."
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def local_runtime_status() -> str:
    """Show the local runtime entrypoint and confirm that explicit local opt-in is required."""
    return "\n".join(
        [
            f"repo_root={REPO_ROOT}",
            f"run_pipeline={RUN_PIPELINE}",
            "backend=ollama",
            "default_mode=exhaustive",
            "auto_review=enabled",
            "explicit_opt_in=required",
        ]
    )


if __name__ == "__main__":
    mcp.run()
