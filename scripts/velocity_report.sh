#!/bin/bash
# velocity_report.sh - Print weekly velocity report and 100-task forecast.
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
if forecast.get(chr(39)+'estimated_done'+chr(39)):
    print('Forecast: {} for next 100 tasks (confidence: {})'.format(
          forecast['estimated_done'], forecast['confidence']))
else:
    print('Forecast: not enough data yet')
"
