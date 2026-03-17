#!/usr/bin/env python3
import json
import pathlib


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
OUTPUT_PATH = REPO_ROOT / "state" / "private-tool-registry.json"


def main():
    tools = []
    for path in sorted(SCRIPTS_DIR.glob("*.sh")):
        if path.name in {"start_local_cli.sh", "progress_tracker.sh"}:
            continue
        tools.append({
            "id": path.stem,
            "path": str(path.relative_to(REPO_ROOT)),
        })
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"tools": tools}, indent=2) + "\n")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
