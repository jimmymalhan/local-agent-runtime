#!/usr/bin/env python3
import argparse
import json
import pathlib
import subprocess
import sys


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = json.loads((REPO_ROOT / "config" / "runtime.json").read_text())
OUTPUT_PATH = REPO_ROOT / "state" / "model-registry.json"


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def installed_models():
    output = run(["ollama", "list"]).stdout.splitlines()
    models = []
    for line in output[1:]:
        parts = line.split()
        if not parts:
            continue
        item = {"name": parts[0]}
        if len(parts) > 1:
            item["id"] = parts[1]
        if len(parts) > 2:
            item["size"] = parts[2]
        models.append(item)
    return models


def resolve_team(installed):
    names = {item["name"] for item in installed}
    items = []
    for role in RUNTIME.get("team_order", list(RUNTIME.get("team", {}).keys())):
        cfg = RUNTIME["team"][role]
        model = cfg.get("model", RUNTIME["default_model"])
        items.append(
            {
                "role": role,
                "label": cfg.get("label", role),
                "model": model,
                "installed": model in names,
                "weight": cfg.get("weight", 0),
            }
        )
    return items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    installed = installed_models()
    payload = {
      "default_model": RUNTIME["default_model"],
      "installed_models": installed,
      "team": resolve_team(installed),
    }
    if args.write:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    if args.json:
        print(json.dumps(payload, indent=2))
        return
    print(f"default_model={payload['default_model']}")
    print(f"installed_models={len(installed)}")
    for item in payload["team"]:
        suffix = "installed" if item["installed"] else "missing"
        print(f"{item['label']}: {item['model']} | weight {item['weight']} | {suffix}")
    if installed:
        print("")
        print("All installed models:")
        for item in installed:
            print(f"- {item['name']}")


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError:
        print("ollama is not installed or not on PATH", file=sys.stderr)
        raise SystemExit(1)
