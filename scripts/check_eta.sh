#!/usr/bin/env bash
# scripts/check_eta.sh — Quick check of ETA to beat Opus 4.6

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

python3 scripts/eta_calculator.py "$@"
