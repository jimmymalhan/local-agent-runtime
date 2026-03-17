#!/bin/bash
# A placeholder script for running an AutoGen workflow.
#
# AutoGen is a multi-agent framework that supports asynchronous collaboration and
# human-in-the-loop execution【237246115056748†L164-L176】.  This wrapper runs a Python
# script that defines agents and tasks using AutoGen.

SCRIPT_PATH=${1:-./autogen_workflow.py}

if ! command -v python >/dev/null 2>&1; then
  echo "Python is required to run AutoGen workflows." >&2
  exit 1
fi

if [ ! -f "$SCRIPT_PATH" ]; then
  cat <<EOF >&2
Cannot find '$SCRIPT_PATH'.
Create a Python script that uses AutoGen to define your agents and tasks and
pass its path to this wrapper.  For example:

  python -m venv .venv && source .venv/bin/activate
  pip install autogen
  echo "from autogen import *  # build your agents and tasks here" > my_autogen.py
  ./scripts/autogen_run.sh my_autogen.py

EOF
  exit 1
fi

echo "Running AutoGen workflow defined in '$SCRIPT_PATH'..."
python "$SCRIPT_PATH"
