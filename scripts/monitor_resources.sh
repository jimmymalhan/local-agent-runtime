#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
THRESHOLD=${THRESHOLD:-$(python3 -c "import json; print(json.load(open('$REPO_ROOT/config/runtime.json')).get('resource_limits',{}).get('cpu_percent',90))" 2>/dev/null || echo 90)}
LOG_DIR="$SCRIPT_DIR/../logs"
STATE_DIR="$SCRIPT_DIR/../state"
mkdir -p "$LOG_DIR" "$STATE_DIR"
LOG_FILE="$LOG_DIR/resource_usage.log"
SLOWDOWN_FILE="$STATE_DIR/slowdown.flag"

echo "$(date '+%Y-%m-%d %H:%M:%S') - Resource monitor started (threshold ${THRESHOLD}%)" >> "$LOG_FILE"

while true; do
    STATUS=$(python3 "$SCRIPT_DIR/resource_status.py")
    CPU=$(python3 - "$REPO_ROOT" <<'PY'
import json, pathlib, sys
data = json.loads((pathlib.Path(sys.argv[1]) / "state" / "resource-status.json").read_text())
print(int(round(data.get("cpu_percent", 0))))
PY
)
    MEM=$(python3 - "$REPO_ROOT" <<'PY'
import json, pathlib, sys
data = json.loads((pathlib.Path(sys.argv[1]) / "state" / "resource-status.json").read_text())
print(int(round(data.get("memory_percent", 0))))
PY
)

    echo "$(date '+%Y-%m-%d %H:%M:%S') - $STATUS" >> "$LOG_FILE"

    if [ "$CPU" -gt "$THRESHOLD" ] || [ "$MEM" -gt "$THRESHOLD" ]; then
        echo "slowdown" > "$SLOWDOWN_FILE"
    else
        rm -f "$SLOWDOWN_FILE"
    fi

    sleep 5
done
