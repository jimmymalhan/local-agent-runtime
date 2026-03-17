#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys


PLAN_GATE_TEXT = "Upgrade to GitHub Pro or make this repository public"


class GhError(RuntimeError):
    pass


def run_gh(args: list[str]) -> str:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout).strip()
        raise GhError(message)
    return proc.stdout


def repo_view(repo: str) -> dict:
    return json.loads(run_gh(["repo", "view", repo, "--json", "nameWithOwner,visibility"]))


def branch_protection(repo: str, branch: str) -> dict:
    return json.loads(run_gh(["api", f"repos/{repo}/branches/{branch}/protection"]))


def protection_status(repo: str, branch: str) -> dict:
    repo_info = repo_view(repo)
    result = {
        "repo": repo_info["nameWithOwner"],
        "visibility": repo_info["visibility"],
        "branch": branch,
        "protected": False,
        "status": "unprotected",
        "required_checks": [],
        "blocker": "",
    }
    try:
        protection = branch_protection(repo, branch)
    except GhError as exc:
        message = str(exc)
        if PLAN_GATE_TEXT in message and repo_info["visibility"] == "PRIVATE":
            result["status"] = "blocked_by_plan"
            result["blocker"] = (
                "GitHub does not allow branch protection or rulesets for this private repo on the current plan. "
                "Make the repo public or upgrade the plan before retrying."
            )
        else:
            result["status"] = "api_error"
            result["blocker"] = message
        return result

    checks = protection.get("required_status_checks", {}) or {}
    contexts = checks.get("contexts", []) or []
    result["protected"] = True
    result["status"] = "protected"
    result["required_checks"] = contexts
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="jimmymalhan/local-agent-runtime")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = protection_status(args.repo, args.branch)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"repo={result['repo']}")
        print(f"branch={result['branch']}")
        print(f"visibility={result['visibility']}")
        print(f"status={result['status']}")
        print(f"protected={str(result['protected']).lower()}")
        if result["required_checks"]:
            print("required_checks=" + ",".join(result["required_checks"]))
        if result["blocker"]:
            print(f"blocker={result['blocker']}")
    return 0 if result["protected"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
