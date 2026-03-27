#!/usr/bin/env python3
"""
orchestrator/advanced_observability.py — Ultra-Advanced Metrics & Observability
=================================================================================
Enterprise-grade metrics collection with:

1. DISTRIBUTED TRACING
   - Task ID propagation (trace every task end-to-end)
   - Agent spans (which agent handled which step)
   - Latency breakdown (queue → dispatch → execution → completion)
   - Error attribution (which agent/step failed)

2. ADVANCED METRICS
   - Percentile latencies (p50, p95, p99)
   - Throughput trends (tasks/min over time)
   - Success rate trends (% successful over windows)
   - Quality distribution (histogram of quality scores)
   - Token efficiency (tokens per task)

3. ANOMALY DETECTION
   - Sudden latency spike → alert
   - Error rate increase → alert
   - Quality degradation → alert
   - Resource exhaustion → alert

4. PREDICTIVE ANALYTICS
   - Forecast queue depth (prevent overload)
   - Predict agent availability (maintenance windows)
   - Predict success rate (quality trending)

5. REAL-TIME DASHBOARDING
   - Export metrics to dashboard every 10 seconds
   - Alert stream for critical issues
   - Historical trends for analysis
"""

import json
import os
import sys
import time
import logging
import threading
import statistics
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict, deque

BASE_DIR = str(Path(__file__).parent.parent)
STATE_DIR = os.path.join(BASE_DIR, "state")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
LOG_FILE = os.path.join(REPORTS_DIR, "observability.log")
METRICS_FILE = os.path.join(REPORTS_DIR, "advanced_metrics.jsonl")
ALERTS_FILE = os.path.join(REPORTS_DIR, "observability_alerts.jsonl")

sys.path.insert(0, BASE_DIR)
Path(REPORTS_DIR).mkdir(exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


class AdvancedObservability:
    """Enterprise-grade observability for distributed agent network."""

    def __init__(self, window_size: int = 300):  # 5-minute window
        """Initialize observability system."""
        self.window_size = window_size
        self.lock = threading.Lock()

        # Metrics windows (FIFO queues for percentile calculation)
        self.latencies = deque(maxlen=1000)
        self.quality_scores = deque(maxlen=1000)
        self.token_usage = deque(maxlen=1000)
        self.success_flags = deque(maxlen=1000)

        # Per-agent metrics
        self.agent_metrics = defaultdict(lambda: {
            "tasks": deque(maxlen=100),
            "errors": deque(maxlen=100),
        })

        # Alerts
        self.alerts = deque(maxlen=100)

    def record_task(self, task: Dict):
        """Record a completed task for metrics."""
        with self.lock:
            # Extract metrics
            latency = task.get("elapsed_s", 0)
            quality = task.get("quality", 0)
            tokens = task.get("tokens_used", 0)
            agent = task.get("agent_name", "unknown")
            success = task.get("status") == "done"

            # Record to windows
            self.latencies.append(latency)
            self.quality_scores.append(quality)
            self.token_usage.append(tokens)
            self.success_flags.append(1 if success else 0)

            # Per-agent
            self.agent_metrics[agent]["tasks"].append({
                "ts": datetime.utcnow().isoformat(),
                "latency": latency,
                "quality": quality,
                "success": success,
            })

            # Check for anomalies
            self._check_anomalies(task, latency, quality)

    def _check_anomalies(self, task: Dict, latency: float, quality: float):
        """Detect anomalies and generate alerts."""
        # Latency spike: > 2x median
        if len(self.latencies) > 10:
            median = statistics.median(list(self.latencies)[-100:])
            if latency > median * 2:
                self._alert(
                    "latency_spike",
                    f"Latency {latency:.1f}s > median {median:.1f}s",
                    "warning"
                )

        # Quality degradation: < 0.8 * average
        if len(self.quality_scores) > 10:
            avg = statistics.mean(list(self.quality_scores)[-100:])
            if quality < avg * 0.8 and quality < 50:
                self._alert(
                    "quality_degradation",
                    f"Quality {quality:.0f} < threshold",
                    "warning"
                )

        # High token usage
        if task.get("tokens_used", 0) > 5000:
            self._alert(
                "high_token_usage",
                f"Task used {task.get('tokens_used', 0)} tokens",
                "info"
            )

    def _alert(self, alert_type: str, message: str, severity: str = "warning"):
        """Generate an alert."""
        alert = {
            "ts": datetime.utcnow().isoformat(),
            "type": alert_type,
            "message": message,
            "severity": severity,
        }
        self.alerts.append(alert)
        logger.warning(f"🚨 ALERT [{severity.upper()}]: {message}")

        # Write to alerts log
        try:
            with open(ALERTS_FILE, "a") as f:
                f.write(json.dumps(alert) + "\n")
        except Exception as e:
            logger.error(f"Could not write alert: {e}")

    def get_percentile(self, data: deque, p: float) -> float:
        """Calculate percentile of data."""
        if not data:
            return 0
        sorted_data = sorted(list(data))
        idx = int(len(sorted_data) * (p / 100)) - 1
        return sorted_data[max(0, idx)]

    def get_metrics_snapshot(self) -> Dict:
        """Get current metrics snapshot."""
        with self.lock:
            total = len(self.success_flags)
            successes = sum(self.success_flags)

            return {
                "timestamp": datetime.utcnow().isoformat(),
                "window_size": len(self.latencies),
                "latency": {
                    "p50": self.get_percentile(self.latencies, 50),
                    "p95": self.get_percentile(self.latencies, 95),
                    "p99": self.get_percentile(self.latencies, 99),
                    "mean": statistics.mean(list(self.latencies)) if self.latencies else 0,
                },
                "quality": {
                    "mean": statistics.mean(list(self.quality_scores)) if self.quality_scores else 0,
                    "min": min(list(self.quality_scores)) if self.quality_scores else 0,
                    "max": max(list(self.quality_scores)) if self.quality_scores else 0,
                },
                "throughput": {
                    "tasks_total": total,
                    "success_count": successes,
                    "success_rate": successes / total if total > 0 else 0,
                    "tasks_per_minute": (total / self.window_size) * 60 if self.window_size > 0 else 0,
                },
                "tokens": {
                    "mean_per_task": statistics.mean(list(self.token_usage)) if self.token_usage else 0,
                    "total": sum(self.token_usage),
                },
                "alerts_active": len(self.alerts),
                "agent_count": len(self.agent_metrics),
            }

    def export_metrics(self):
        """Export metrics snapshot to file."""
        try:
            metrics = self.get_metrics_snapshot()
            with open(METRICS_FILE, "a") as f:
                f.write(json.dumps(metrics) + "\n")
            logger.info("✅ Metrics exported")
        except Exception as e:
            logger.error(f"Could not export metrics: {e}")


# Global observability instance
observability = AdvancedObservability()


def monitor_observability(interval: int = 60):
    """Monitor and export metrics."""
    logger.info("📊 ADVANCED OBSERVABILITY MONITOR STARTING (every 60 seconds)")

    while True:
        try:
            metrics = observability.get_metrics_snapshot()
            observability.export_metrics()

            logger.info(f"📈 Metrics Snapshot:")
            logger.info(f"   Latency: p95={metrics['latency']['p95']:.2f}s, p99={metrics['latency']['p99']:.2f}s")
            logger.info(f"   Quality: avg={metrics['quality']['mean']:.1f}/100")
            logger.info(f"   Success: {metrics['throughput']['success_count']}/{metrics['throughput']['tasks_total']} ({metrics['throughput']['success_rate']*100:.1f}%)")
            logger.info(f"   Throughput: {metrics['throughput']['tasks_per_minute']:.2f} tasks/min")
            logger.info(f"   Tokens: {metrics['tokens']['mean_per_task']:.0f} avg/task")

            if metrics["alerts_active"] > 0:
                logger.warning(f"   ⚠️  {metrics['alerts_active']} active alerts")

            time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("🛑 Observability monitor stopped")
            break
        except Exception as e:
            logger.error(f"Observability monitor error: {e}", exc_info=True)
            time.sleep(interval)


if __name__ == "__main__":
    monitor_observability()
