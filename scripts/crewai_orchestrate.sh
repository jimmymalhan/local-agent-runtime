#!/bin/bash
# A wrapper script for running a CrewAI project.
#
# CrewAI is an open‑source framework designed to coordinate multiple agents in
# structured, role‑based workflows【534472104224777†L122-L141】.  This script
# checks whether the CrewAI CLI is installed and runs a project located at
# the specified directory.  See docs/AI_FRAMEWORKS.md for details.

PROJECT_DIR=${1:-.}

if ! command -v crewai >/dev/null 2>&1; then
  echo "CrewAI CLI is not installed. Install it with 'pip install crewai' or 'uv tool install crewai'." >&2
  exit 1
fi

if [ ! -d "$PROJECT_DIR" ]; then
  echo "Project directory '$PROJECT_DIR' does not exist." >&2
  exit 1
fi

# Run the CrewAI project.  Users should create agents.yaml and tasks.yaml inside
# the project directory according to the CrewAI documentation.
echo "Launching CrewAI project in '$PROJECT_DIR'..."
crewai run "$PROJECT_DIR"
