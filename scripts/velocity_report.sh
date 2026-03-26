#!/bin/bash
# velocity_report.sh — Print weekly velocity report and 100-task forecast.
# Usage: bash scripts/velocity_report.sh
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -c "
import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'local-agents')
from reports.velocity_tracker import VelocityTracker
t = VelocityTracker()
print(t.weekly_report())
vel = t.velocity(7)
forecast = t.forecast(100)
if forecast['estimated_done']:
    print(f'Forecast: {forecast[\"estimated_done\"]} for next 100 tasks (confidence: {forecast[\"confidence\"]})')
else:
    print('Forecast: not enough data yet (no tasks logged in last 7 days)')
"
