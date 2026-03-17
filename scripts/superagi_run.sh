#!/bin/bash
# A placeholder script for running a SuperAGI project.
#
# SuperAGI supports parallel execution of agents and includes a built-in UI for
# managing workflows【237246115056748†L224-L236】.  This wrapper checks for the
# 'superagi' CLI and launches a project.

PROJECT_DIR=${1:-.}

if ! command -v superagi >/dev/null 2>&1; then
  echo "SuperAGI CLI is not installed. Install it with 'pip install superagi'." >&2
  exit 1
fi

if [ ! -d "$PROJECT_DIR" ]; then
  echo "Project directory '$PROJECT_DIR' does not exist." >&2
  exit 1
fi

echo "Launching SuperAGI project in '$PROJECT_DIR'..."
superagi "$PROJECT_DIR"
