#!/bin/bash
# run-agents.sh — Wrapper to properly start the continuous loop

export PYTHONPATH="/Users/jimmymalhan/Documents/local-agent-runtime/local-agents:$PYTHONPATH"
cd /Users/jimmymalhan/Documents/local-agent-runtime/local-agents
exec /usr/bin/python3 -m orchestrator.continuous_loop --forever --project all
