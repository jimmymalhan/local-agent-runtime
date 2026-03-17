#!/bin/bash
# A placeholder script for running a LangGraph flow.
#
# LangGraph provides graph-based orchestration on top of LangChain, ideal for
# long-running, stateful workflows with error recovery【237246115056748†L146-L156】.
# Use this wrapper to run a LangGraph flow defined in a Python module.

FLOW_MODULE=${1:-langgraph_flow}

if ! command -v python >/dev/null 2>&1; then
  echo "Python is required to run LangGraph flows." >&2
  exit 1
fi

python - <<PYEOF
try:
    import importlib
    module = importlib.import_module('$FLOW_MODULE')
    if hasattr(module, 'run'):
        module.run()
    else:
        print(f"Module '$FLOW_MODULE' does not define a 'run' function. Please implement run().")
except ImportError as e:
    print(f"Could not import module '$FLOW_MODULE': {e}")
    print("Ensure that langgraph is installed (pip install langgraph) and the module exists.")
PYEOF
