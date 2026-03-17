#!/bin/bash
# A placeholder script for running a LangChain pipeline locally.
#
# LangChain offers a modular approach to building AI agents by chaining LLMs with
# tools, memory modules and external sources【237246115056748†L125-L137】.  This
# wrapper demonstrates how you might invoke a LangChain script.

SCRIPT_PATH=${1:-./langchain_pipeline.py}

if ! command -v python >/dev/null 2>&1; then
  echo "Python is required to run LangChain pipelines." >&2
  exit 1
fi

if [ ! -f "$SCRIPT_PATH" ]; then
  cat <<EOF >&2
Cannot find '$SCRIPT_PATH'.
Create a Python script that uses LangChain to build your pipeline and pass its
path to this wrapper.  For example:

  python -m venv .venv && source .venv/bin/activate
  pip install langchain
  echo "from langchain import *  # build your chain here" > my_chain.py
  ./scripts/langchain_pipeline.sh my_chain.py

EOF
  exit 1
fi

echo "Running LangChain pipeline defined in '$SCRIPT_PATH'..."
python "$SCRIPT_PATH"
