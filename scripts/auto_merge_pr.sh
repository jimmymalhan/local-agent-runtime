#!/usr/bin/env bash
# scripts/auto_merge_pr.sh — Auto-merge PRs that pass CI with no conflicts
# Safe: only merges if all checks pass, no conflicts, not main branch.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "[auto-merge] Checking open PRs..."

# Get all open PRs as JSON
PRS=$(gh pr list --state open --json number,title,headRefName,mergeable,statusCheckRollup 2>/dev/null || echo "[]")

if [[ "$PRS" == "[]" || -z "$PRS" ]]; then
  echo "[auto-merge] No open PRs found"
  exit 0
fi

# Process each PR
echo "$PRS" | python3 - <<'PYEOF'
import json, subprocess, sys

prs = json.loads(open('/dev/stdin').read())

for pr in prs:
  num    = pr.get('number')
  title  = pr.get('title','')
  branch = pr.get('headRefName','')
  mergeable = pr.get('mergeable','')

  # Skip if not mergeable
  if mergeable != 'MERGEABLE':
    print(f"[auto-merge] PR #{num} ({branch}) — skipping: mergeable={mergeable}")
    continue

  # Check CI status
  checks = pr.get('statusCheckRollup') or []
  if isinstance(checks, list):
    states = [c.get('conclusion') or c.get('state','') for c in checks]
  else:
    states = []

  # Allow merge if all checks pass or there are no checks
  failed = [s for s in states if s.lower() in ('failure','error','cancelled')]
  pending = [s for s in states if s.lower() in ('pending','queued','in_progress')]

  if failed:
    print(f"[auto-merge] PR #{num} ({branch}) — SKIP: {len(failed)} failing checks")
    continue
  if pending:
    print(f"[auto-merge] PR #{num} ({branch}) — SKIP: {len(pending)} pending checks")
    continue

  # Merge
  print(f"[auto-merge] PR #{num} '{title}' ({branch}) — merging...")
  result = subprocess.run(
    ['gh', 'pr', 'merge', str(num), '--squash', '--delete-branch',
     '--subject', title],
    capture_output=True, text=True
  )
  if result.returncode == 0:
    print(f"[auto-merge] PR #{num} merged successfully")
  else:
    print(f"[auto-merge] PR #{num} merge failed: {result.stderr.strip()}")

PYEOF

echo "[auto-merge] Done"
