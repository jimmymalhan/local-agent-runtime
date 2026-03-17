#!/usr/bin/env bash
set -euo pipefail

REPO="${1:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAYLOAD="${SCRIPT_DIR}/../rulesets/main.json"
RULESET_ID="$(gh api "repos/${REPO}/rulesets" --jq '.[] | select(.name=="Protect main" and .target=="branch") | .id' | head -n 1)"

if [[ -n "${RULESET_ID}" ]]; then
  gh api --method PUT "repos/${REPO}/rulesets/${RULESET_ID}" --input "${PAYLOAD}" >/dev/null
  echo "Updated Protect main ruleset for ${REPO}"
else
  gh api --method POST "repos/${REPO}/rulesets" --input "${PAYLOAD}" >/dev/null
  echo "Created Protect main ruleset for ${REPO}"
fi
