#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys


PLAN_GATE_TEXT = "Upgrade to GitHub Pro or make this repository public"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RULESET_PAYLOAD = REPO_ROOT / ".github" / "rulesets" / "main.json"


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


def repo_rulesets(repo: str) -> list[dict]:
    return json.loads(run_gh(["api", f"repos/{repo}/rulesets"]))


def repo_ruleset(repo: str, ruleset_id: int) -> dict:
    return json.loads(run_gh(["api", f"repos/{repo}/rulesets/{ruleset_id}"]))


def ruleset_matches_branch(ruleset: dict, branch: str) -> bool:
    if ruleset.get("target") != "branch":
        return False
    conditions = ruleset.get("conditions", {}) or {}
    ref_name = conditions.get("ref_name", {}) or {}
    include = ref_name.get("include", []) or []
    exclude = ref_name.get("exclude", []) or []
    ref = f"refs/heads/{branch}"
    if include and ref not in include:
        return False
    if ref in exclude:
        return False
    return True


def required_checks_from_ruleset(ruleset: dict) -> list[str]:
    checks = []
    for rule in ruleset.get("rules", []) or []:
        if rule.get("type") != "required_status_checks":
            continue
        params = rule.get("parameters", {}) or {}
        for item in params.get("required_status_checks", []) or []:
            context = item.get("context")
            if context:
                checks.append(context)
    return checks


def sync_ruleset(repo: str) -> dict:
    existing = repo_rulesets(repo)
    payload = json.loads(RULESET_PAYLOAD.read_text())
    current = next((item for item in existing if item.get("name") == payload.get("name") and item.get("target") == payload.get("target")), None)
    if current:
        return json.loads(run_gh(["api", "--method", "PUT", f"repos/{repo}/rulesets/{current['id']}", "--input", str(RULESET_PAYLOAD)]))
    return json.loads(run_gh(["api", "--method", "POST", f"repos/{repo}/rulesets", "--input", str(RULESET_PAYLOAD)]))


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
        "protection_source": "",
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
            return result
        try:
            rulesets = repo_rulesets(repo)
        except GhError:
            result["status"] = "api_error"
            result["blocker"] = message
            return result
        detailed_rulesets = []
        for item in rulesets:
            if item.get("enforcement") != "active":
                continue
            detailed = item
            if "rules" not in item or "conditions" not in item:
                try:
                    detailed = repo_ruleset(repo, int(item["id"]))
                except (GhError, KeyError, ValueError):
                    detailed = item
            detailed_rulesets.append(detailed)
        matching = [item for item in detailed_rulesets if ruleset_matches_branch(item, branch)]
        if not matching:
            if "Branch not protected" in message:
                result["status"] = "unprotected"
                result["blocker"] = "No active branch protection or matching repository ruleset found for main."
            else:
                result["status"] = "api_error"
                result["blocker"] = message
            return result
        required_checks = []
        for item in matching:
            required_checks.extend(required_checks_from_ruleset(item))
        deduped = []
        for item in required_checks:
            if item not in deduped:
                deduped.append(item)
        result["protected"] = True
        result["status"] = "protected"
        result["required_checks"] = deduped
        result["protection_source"] = "ruleset"
        return result

    checks = protection.get("required_status_checks", {}) or {}
    contexts = checks.get("contexts", []) or []
    result["protected"] = True
    result["status"] = "protected"
    result["required_checks"] = contexts
    result["protection_source"] = "branch_protection"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="jimmymalhan/local-agent-runtime")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--sync", action="store_true")
    args = parser.parse_args()

    if args.sync:
        synced = sync_ruleset(args.repo)
        if not args.json:
            print(f"synced_ruleset={synced.get('name', '')}")
            print(f"ruleset_id={synced.get('id', '')}")
    result = protection_status(args.repo, args.branch)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"repo={result['repo']}")
        print(f"branch={result['branch']}")
        print(f"visibility={result['visibility']}")
        print(f"status={result['status']}")
        print(f"protected={str(result['protected']).lower()}")
        if result["protection_source"]:
            print(f"source={result['protection_source']}")
        if result["required_checks"]:
            print("required_checks=" + ",".join(result["required_checks"]))
        if result["blocker"]:
            print(f"blocker={result['blocker']}")
    return 0 if result["protected"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
