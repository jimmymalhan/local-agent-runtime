#!/bin/bash
# Manage the TODO list for the local session framework.
# Usage:
#   update_todo.sh add "<description>" "<agents>"
#   update_todo.sh done "<pattern>"
#   update_todo.sh list

set -euo pipefail

TODO_FILE="$(dirname "$0")/../state/todo.md"

if [ ! -f "$TODO_FILE" ]; then
  cat > "$TODO_FILE" <<'EOF'
# TODO List

## Active Work

EOF
fi

MODE=${1:-list}

case "$MODE" in
  add)
    DESCRIPTION=${2:-}
    AGENTS=${3:-local-team}
    if [ -z "$DESCRIPTION" ]; then
      echo "Usage: $0 add \"<description>\" \"<agents>\"" >&2
      exit 1
    fi
    printf -- "- [ ] %s | agents: %s | added: %s\n" "$DESCRIPTION" "$AGENTS" "$(date '+%Y-%m-%d %H:%M:%S')" >> "$TODO_FILE"
    echo "Added to TODO list: $DESCRIPTION"
    ;;
  done)
    PATTERN=${2:-}
    if [ -z "$PATTERN" ]; then
      echo "Usage: $0 done \"<pattern>\"" >&2
      exit 1
    fi
    python3 - "$TODO_FILE" "$PATTERN" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
pattern = sys.argv[2]
lines = path.read_text().splitlines()
updated = []
done = False
for line in lines:
    if not done and line.startswith("- [ ]") and pattern in line:
        updated.append(line.replace("- [ ]", "- [x]", 1) + f" | completed: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        done = True
    else:
        updated.append(line)
path.write_text("\n".join(updated) + "\n")
print("marked_done" if done else "not_found")
PY
    ;;
  list)
    sed -n '1,240p' "$TODO_FILE"
    ;;
  *)
    echo "Usage: $0 {add|done|list} ..." >&2
    exit 1
    ;;
esac
