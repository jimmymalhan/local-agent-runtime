#!/usr/bin/env python3
import pathlib
import subprocess
import sys


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "logs" / "review-current-changes.md"


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def recent_files(target_repo, limit=20):
    ignored = {"checkpoints", "logs", "memory", "__pycache__"}
    items = []
    for path in target_repo.rglob("*"):
        if not path.is_file():
            continue
        if any(part in ignored for part in path.parts):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        items.append((stat.st_mtime, path))
    items.sort(reverse=True)
    return [str(path) for _, path in items[:limit]]


def main():
    target_repo = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    git_dir = run(["git", "-C", str(target_repo), "rev-parse", "--git-dir"])
    if git_dir.returncode != 0:
        files = "\n".join(recent_files(target_repo)) or "No recent files found."
        body = (
            f"# Current Change Review\n\nTarget repo: {target_repo}\n\n"
            "This path is not a git repository.\n\n"
            "## Recently Changed Files\n"
            f"{files}\n"
        )
        OUTPUT_PATH.write_text(body)
        print(body)
        return

    status = run(["git", "-C", str(target_repo), "status", "--short", "--branch"]).stdout.strip()
    diff_stat = run(["git", "-C", str(target_repo), "diff", "--stat"]).stdout.strip()
    staged_stat = run(["git", "-C", str(target_repo), "diff", "--cached", "--stat"]).stdout.strip()
    names = run(["git", "-C", str(target_repo), "diff", "--name-only"]).stdout.strip()
    staged_names = run(["git", "-C", str(target_repo), "diff", "--cached", "--name-only"]).stdout.strip()

    parts = [
        "# Current Change Review",
        "",
        f"Target repo: {target_repo}",
        "",
        "## Status",
        status or "No changes.",
        "",
        "## Unstaged Diff Stat",
        diff_stat or "No unstaged diff.",
        "",
        "## Staged Diff Stat",
        staged_stat or "No staged diff.",
        "",
        "## Unstaged Files",
        names or "None",
        "",
        "## Staged Files",
        staged_names or "None",
        "",
    ]
    body = "\n".join(parts) + "\n"
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(body)
    print(body)


if __name__ == "__main__":
    main()
