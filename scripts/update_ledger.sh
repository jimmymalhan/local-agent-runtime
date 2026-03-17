#!/bin/bash
# Update a simple ledger for resource consumption and task outcomes.
#
# This script appends entries to state/ledger.md to track the
# approximate cost of running each agent in the pipeline.  It reads
# the latest CPU and memory usage from the resource usage log and
# estimates energy consumption and electricity cost based on Mac mini
# power characteristics from Apple's environmental report and
# third‑party measurements.  The ledger helps the system stay
# mindful of resource usage and encourages efficient, revenue‑focused
# operation.

# Constants (you can adjust these based on your hardware and local
# electricity costs).  Idle power and max power values come from
# Apple's Mac mini environmental report, where idle power is around
# 10.6 W and maximum continuous power is 150 W【393848199723883†L446-L473】.  Cost per kWh is
# approximated at 0.15 USD, similar to estimates used by the power
# consumption database【566118046755280†L16-L21】.
IDLE_POWER_W=10.6
MAX_POWER_W=150
COST_PER_KWH=0.15

AGENT_NAME="$1"
if [ -z "$AGENT_NAME" ]; then
  echo "Usage: $0 <agent-name>" >&2
  exit 1
fi

STATE_DIR="$(dirname "$0")/../state"
LOG_DIR="$(dirname "$0")/../logs"
LEDGER_FILE="$STATE_DIR/ledger.md"
RESOURCE_LOG="$LOG_DIR/resource_usage.log"

mkdir -p "$STATE_DIR"

# Initialise the ledger with a header if it doesn't exist
if [ ! -f "$LEDGER_FILE" ]; then
  cat > "$LEDGER_FILE" <<EOF_LEDGER
# Resource Ledger

This ledger tracks the approximate energy consumption and cost of each agent run.  It is intended for
internal optimisation and profit‑and‑loss (P&L) awareness.  Power estimates are based on Mac mini
measurements (idle 10.6 W, maximum 150 W)【393848199723883†L446-L473】 and a cost of 0.15 USD per kWh【566118046755280†L16-L21】.

| Timestamp | Agent | CPU (%) | MEM (%) | Est. Power (W) | Est. Energy (kWh) | Est. Cost (USD) | Comment |
|---|---|---|---|---|---|---|---|
EOF_LEDGER
fi

# Extract the latest CPU and memory usage from the resource log.  If the log
# doesn’t exist or has no data, default to 0%.
if [ -f "$RESOURCE_LOG" ] && grep -q "High usage detected" "$RESOURCE_LOG"; then
  last_line=$(grep "High usage detected" "$RESOURCE_LOG" | tail -n 1)
  # Extract CPU and MEM percentages from the pattern "CPU=xx% MEM=yy%"
  CPU=$(echo "$last_line" | sed -n 's/.*CPU=\([0-9]*\)%.*$/\1/p')
  MEM=$(echo "$last_line" | sed -n 's/.*MEM=\([0-9]*\)%.*$/\1/p')
  # If parsing failed, set to zero
  CPU=${CPU:-0}
  MEM=${MEM:-0}
else
  CPU=0
  MEM=0
fi

# Estimate power draw as linear interpolation between idle and max based on CPU.
POWER_W=$(python3 -c "idle=$IDLE_POWER_W; maxp=$MAX_POWER_W; cpu=$CPU; print(round(idle + (maxp-idle)*cpu/100, 2))")
# Estimate energy consumed for a 10 second interval (matching monitor sampling)
ENERGY_KWH=$(python3 -c "p=$POWER_W; print(round((p/1000)*(10/3600), 6))")
# Estimate cost
COST=$(python3 -c "energy=$ENERGY_KWH; cost_per_kwh=$COST_PER_KWH; print(round(energy*cost_per_kwh, 6))")

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Append entry to ledger
echo "| $TIMESTAMP | $AGENT_NAME | $CPU | $MEM | $POWER_W | $ENERGY_KWH | $COST | Auto‑generated entry |" >> "$LEDGER_FILE"

echo "update_ledger: recorded entry for agent $AGENT_NAME (CPU=$CPU, MEM=$MEM, Power=$POWER_W W, Energy=$ENERGY_KWH kWh, Cost=\$${COST})." >&2
exit 0
