#!/bin/bash
# Update the local agent project.
#
# This helper script performs a series of maintenance tasks to ensure
# that your local agent repository stays up to date.  It runs the
# external tool discovery, self‑update of the repository and
# frameworks, and the skill generator to create or refine skills
# automatically.  Only the parts that make sense in the current
# environment are executed.  For example, network access is required
# for external tool discovery and repository updates.

set -e

SCRIPT_DIR="$(dirname "$0")"
REPO_DIR="$SCRIPT_DIR/.."

echo "[update_project] Starting project maintenance..." >&2

# 1. Discover and integrate new external tools if EXTERNAL_TOOL_SOURCE is set.
if [ -n "${EXTERNAL_TOOL_SOURCE:-}" ]; then
  echo "[update_project] Updating external tools from \$EXTERNAL_TOOL_SOURCE" >&2
  "$SCRIPT_DIR/update_external_tools.sh" || echo "[update_project] External tool update failed" >&2
else
  echo "[update_project] EXTERNAL_TOOL_SOURCE not set; skipping external tool discovery" >&2
fi

# 2. Perform a git pull to update the repository, if .git directory exists.
if [ -d "$REPO_DIR/.git" ]; then
  echo "[update_project] Checking for repository updates..." >&2
  git -C "$REPO_DIR" fetch origin || echo "[update_project] git fetch failed" >&2
  LOCAL=$(git -C "$REPO_DIR" rev-parse @ 2>/dev/null || echo "")
  REMOTE=$(git -C "$REPO_DIR" rev-parse @{u} 2>/dev/null || echo "")
  if [ -n "$LOCAL" ] && [ -n "$REMOTE" ] && [ "$LOCAL" != "$REMOTE" ]; then
    echo "[update_project] Local repository is behind; pulling changes..." >&2
    git -C "$REPO_DIR" pull --ff-only || echo "[update_project] git pull failed" >&2
  else
    echo "[update_project] Repository is up to date" >&2
  fi
else
  echo "[update_project] Not a git repository; skipping pull" >&2
fi

# 3. Upgrade Python dependencies for optional frameworks if pip is available.
if command -v pip >/dev/null 2>&1; then
  echo "[update_project] Upgrading optional Python frameworks" >&2
  pip install --quiet --upgrade \
    crewai langchain langgraph autogen superagi llama-index \
    google-adk dify semantic-kernel pydantic-ai-agents strands-agents \
    smolagents agno ms-agent-framework || echo "[update_project] Some packages could not be upgraded" >&2
else
  echo "[update_project] pip not available; skipping package upgrades" >&2
fi

# 4. Generate or update skills based on feedback logs.
echo "[update_project] Generating new skills from feedback logs" >&2
bash "$SCRIPT_DIR/skill_generator.sh" || echo "[update_project] Skill generator encountered an error" >&2

# 5. Generate or update role definitions from the org structure.
echo "[update_project] Generating role definitions from org structure" >&2
bash "$SCRIPT_DIR/role_generator.sh" || echo "[update_project] Role generator encountered an error" >&2

echo "[update_project] Project maintenance complete" >&2
exit 0