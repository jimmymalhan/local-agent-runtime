#!/usr/bin/env python3
import json
import pathlib
import subprocess
import sys


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "context" / "project-summary.md"


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def read_head(path, lines=160):
    if not path.exists():
        return ""
    return "".join(path.read_text(errors="ignore").splitlines(True)[:lines])


def top_level_inventory(target_repo):
    entries = []
    for path in sorted(target_repo.iterdir()):
        if path.name.startswith(".git"):
            continue
        suffix = "/" if path.is_dir() else ""
        entries.append(f"{path.name}{suffix}")
        if len(entries) >= 40:
            break
    return "\n".join(entries)


def _collect_files_python(target_repo, limit=80):
    """Fallback when rg is not installed."""
    out = []
    try:
        for p in target_repo.rglob("*"):
            if p.is_file() and ".git" not in p.parts:
                out.append(str(p))
                if len(out) >= limit:
                    break
    except OSError:
        pass
    return out[:limit]


def _collect_key_files_python(target_repo):
    """Fallback when rg is not installed."""
    patterns = (
        "README*", "AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md",
        "package.json", "pyproject.toml", "Cargo.toml", "go.mod",
        "Makefile", "docker-compose*", "*.md",
    )
    seen = set()
    out = []
    try:
        for p in target_repo.rglob("*"):
            if not p.is_file() or ".git" in p.parts:
                continue
            name = p.name
            for pat in patterns:
                if pat.endswith("*"):
                    if name.startswith(pat[:-1]) or (pat == "*.md" and p.suffix == ".md"):
                        if str(p) not in seen:
                            seen.add(str(p))
                            out.append(str(p))
                            break
                elif name == pat or (pat == "docker-compose*" and name.startswith("docker-compose")):
                    if str(p) not in seen:
                        seen.add(str(p))
                        out.append(str(p))
                    break
            if len(out) >= 30:
                break
    except OSError:
        pass
    return out[:30]


def find_key_files(target_repo):
    try:
        result = run(
            [
                "rg",
                "--files",
                str(target_repo),
                "-g", "README*",
                "-g", "AGENTS.md",
                "-g", "CLAUDE.md",
                "-g", "CONTRIBUTING.md",
                "-g", "package.json",
                "-g", "pyproject.toml",
                "-g", "Cargo.toml",
                "-g", "go.mod",
                "-g", "Makefile",
                "-g", "docker-compose*",
                "-g", "*.md",
            ]
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.splitlines()[:30]
    except (FileNotFoundError, OSError):
        pass
    return _collect_key_files_python(target_repo)


def detect_test_command(target_repo):
    package_json = target_repo / "package.json"
    if package_json.exists():
        try:
            data = json.loads(package_json.read_text(errors="ignore"))
        except json.JSONDecodeError:
            data = {}
        scripts = data.get("scripts", {})
        if isinstance(scripts, dict) and "test" in scripts:
            return "npm test"
    if (target_repo / "pyproject.toml").exists():
        return "pytest"
    if (target_repo / "Cargo.toml").exists():
        return "cargo test"
    if (target_repo / "go.mod").exists():
        return "go test ./..."
    if (target_repo / "Makefile").exists():
        return "make test"
    return "Not detected"


def main():
    target_repo = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    parts = ["# Project Summary", "", f"## Target Repo\n{target_repo}", ""]

    git_status = run(["git", "-C", str(target_repo), "status", "--short", "--branch"]).stdout.strip()
    if git_status:
        parts.extend(["## Git Status", git_status, ""])

    git_recent = run(
        ["git", "-C", str(target_repo), "log", "--oneline", "-5"]
    ).stdout.strip()
    if git_recent:
        parts.extend(["## Recent Commits", git_recent, ""])

    try:
        r = run(["rg", "--files", str(target_repo)])
        file_inventory = r.stdout.splitlines()[:80] if r.returncode == 0 else []
    except (FileNotFoundError, OSError):
        file_inventory = _collect_files_python(target_repo)
    if file_inventory:
        parts.extend(["## File Inventory", "\n".join(file_inventory), ""])

    top_level = top_level_inventory(target_repo)
    if top_level:
        parts.extend(["## Top Level", top_level, ""])

    key_files = find_key_files(target_repo)
    if key_files:
        parts.extend(["## Key Files", "\n".join(key_files), ""])

    parts.extend(["## Test Command", detect_test_command(target_repo), ""])

    for rel in ("README.md", "AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", "package.json", "pyproject.toml"):
        path = target_repo / rel
        text = read_head(path, lines=80)
        if not text:
            continue
        parts.extend([f"## {rel}", text, ""])
        if path.suffix == ".json":
            try:
                parsed = json.loads(path.read_text(errors="ignore"))
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                summary = {
                    key: parsed.get(key)
                    for key in ("name", "private", "type", "packageManager", "scripts")
                    if key in parsed
                }
                parts.extend([f"## {rel} Summary", json.dumps(summary, indent=2), ""])

    for rel in key_files[:10]:
        if pathlib.Path(rel).name in {"README.md", "AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", "package.json", "pyproject.toml"}:
            continue
        text = read_head(target_repo / rel, lines=40)
        if text:
            parts.extend([f"## {rel}", text, ""])

    OUTPUT_PATH.write_text("\n".join(parts))
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
