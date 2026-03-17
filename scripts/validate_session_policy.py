#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

POLICY_RULES = {
    "AGENTS.md": {
        "required": [
            "execute the work in that session end to end",
            "Do not stop at a generated command or ask the user to run the local runtime manually",
            "The local runtime remains opt-in",
        ],
        "forbidden": [
            "ALWAYS respond with the command for the user to run in the local runtime",
            "For implementation requests: output `scripts/run_pipeline.sh",
            "**NEVER** implement, edit, or modify files in this Cursor session.",
        ],
    },
    "CLAUDE.md": {
        "required": [
            "execute the work in that session instead of replying with a command for the user to run",
            "Local runtime is opt-in",
        ],
        "forbidden": [
            "For implementation/coding tasks: Do not use CLAUDE API, Codex, Cursor context, or external APIs. Route into the local runtime",
        ],
    },
    ".cursor/rules/local-only.mdc": {
        "required": [
            "execute the work in-session end to end",
            "Do not stop at a generated command or ask the user to run the local runtime manually",
            "Route implementation to the local runtime only when the user explicitly asks for Local",
        ],
        "forbidden": [
            "**NEVER** use write, edit, or search_replace for implementation tasks.",
            "**ALWAYS** route implementation to the local runtime",
            "Do not implement in this session",
        ],
    },
    "docs/MCP_LOCAL_RUNTIME_SETUP.md": {
        "required": [
            "opt-in path",
            "only when you explicitly want the local runtime",
            "should not automatically call it for ordinary Codex, Claude, or Cursor implementation work",
        ],
        "forbidden": [
            "Once configured, implementation requests will invoke the `run_local_pipeline` tool.",
            "Cursor will call it for implementation work",
        ],
    },
    "docs/SESSION_COMMANDS.md": {
        "required": [
            "Codex, Claude, and Cursor run independently",
            "Use `Local`, `local-codex`, or `local-claude` **only when you explicitly want** the local Ollama runtime",
        ],
        "forbidden": [],
    },
    "mcp-local-runtime/server.py": {
        "required": [
            "Use this only when the user explicitly asks for the local runtime",
            "Do NOT use when the user asks to open Codex, Claude, or Cursor",
            "explicit_opt_in=required",
        ],
        "forbidden": [
            "enforced local-only defaults",
        ],
    },
}


def validate_policy():
    failures = []
    checked = []
    for relative_path, rules in POLICY_RULES.items():
        path = REPO_ROOT / relative_path
        checked.append(relative_path)
        if not path.exists():
            failures.append(f"{relative_path}: missing")
            continue
        content = path.read_text()
        for snippet in rules["required"]:
            if snippet not in content:
                failures.append(f"{relative_path}: missing required snippet: {snippet}")
        for snippet in rules["forbidden"]:
            if snippet in content:
                failures.append(f"{relative_path}: found forbidden snippet: {snippet}")
    return {"checked": checked, "failures": failures}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    args = parser.parse_args()

    result = validate_policy()
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["failures"]:
            print("Session policy validation failed:")
            for item in result["failures"]:
                print(f"- {item}")
        else:
            print("Session policy validation passed.")
            for item in result["checked"]:
                print(f"- {item}")
    raise SystemExit(1 if result["failures"] else 0)


if __name__ == "__main__":
    main()
