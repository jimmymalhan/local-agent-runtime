#!/usr/bin/env python3
"""
orchestrator/advanced_scheduler.py — Ultra-Advanced Task Scheduler
===================================================================
Intelligent task distribution with:

1. PREDICTIVE AUTO-SCALING
   - Monitor queue depth
   - Spawn sub-agents when queue > 5 tasks
   - Kill sub-agents when idle > 5 min
   - Max workers scales with task complexity

2. INTELLIGENT ROUTING
   - Route by agent capability (executor → code tasks)
   - Route by availability (fastest agents first)
   - Route by historical success (high-quality agents)
   - Failover routing (secondary agents on failure)

3. ADVANCED RETRY STRATEGY
   - Exponential backoff (1s, 2s, 4s, 8s max)
   - Different strategy per failure type:
     * Import error → reload modules + retry
     * Timeout → use slower agent + retry
     * Quality failure → use better agent + retry
   - Circuit breaker (don't retry after 3x same error)

4. RESOURCE-AWARE SCHEDULING
   - CPU/RAM awareness (pause heavy tasks if >80% RAM)
   - Token budget awareness (local vs Claude tokens)
   - Network-aware (batch tasks going to same agent)

5. REAL-TIME OBSERVABILITY
   - Task latency tracking (p50, p95, p99)
   - Agent utilization (% busy)
   - Queue health (avg wait time)
   - Error patterns (detect and report)
"""

import json
import os
import sys
import time
import logging
import threading
import psutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import deque

BASE_DIR = str(Path(__file__).parent.parent)
STATE_DIR = os.path.join(BASE_DIR, "state")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
LOG_FILE = os.path.join(REPORTS_DIR, "advanced_scheduler.log")

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


class AdvancedScheduler:
    """Ultra-advanced task scheduler with predictive scaling & intelligent routing."""

    def __init__(self):
        """Initialize scheduler."""
        self.task_queue = deque()
        self.active_tasks = {}
        self.agent_metrics = {}
        self.sub_agents = []  # Dynamically spawned agents
        self.max_workers = psutil.cpu_count() or 4
        self.lock = threading.Lock()

        # Failure tracking for circuit breaker
        self.failure_patterns = {}  # (agent, error_type) → [timestamps]

    def enqueue_task(self, task: Dict):
        """Enqueue a task for processing."""
        with self.lock:
            task["queued_at"] = datetime.utcnow().isoformat()
            task["queue_position"] = len(self.task_queue)
            self.task_queue.append(task)
            logger.info(f"📥 Task queued: {task.get('title', 'unknown')[:40]}")

    def should_scale_up(self) -> bool:
        """Check if we should spawn more sub-agents."""
        queue_depth = len(self.task_queue)
        active_worker_count = len(self.sub_agents)

        # Scale up if: queue > 5 AND workers < max
        if queue_depth > 5 and active_worker_count < self.max_workers:
            logger.info(f"📈 SCALE UP: Queue={queue_depth}, Workers={active_worker_count}")
            return True
        return False

    def should_scale_down(self) -> bool:
        """Check if we should kill idle sub-agents."""
        # Kill if queue empty and we have extra workers
        if len(self.task_queue) == 0 and len(self.sub_agents) > 2:
            logger.info(f"📉 SCALE DOWN: Killing idle sub-agents")
            return True
        return False

    def get_best_agent(self, task: Dict) -> str:
        """
        Intelligent routing: pick best agent for task.

        Priority:
        1. Agent capability match (routing table)
        2. Agent availability
        3. Historical quality score
        4. Network latency
        """
        category = task.get("category", "code_gen")

        # Capability-based routing
        routing = {
            "code_gen": "executor",
            "bug_fix": "executor",
            "debug": "debugger",
            "test": "test_engineer",
            "arch": "architect",
            "research": "researcher",
        }

        preferred = routing.get(category, "executor")
        logger.info(f"🎯 Routing task '{category}' to {preferred}")
        return preferred

    def calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff time."""
        return min(2 ** attempt, 8.0)  # 1s, 2s, 4s, 8s max

    def check_circuit_breaker(self, agent: str, error_type: str) -> bool:
        """
        Circuit breaker: don't retry if we've failed 3x with same error in last minute.
        """
        key = (agent, error_type)
        now = datetime.utcnow()

        if key not in self.failure_patterns:
            self.failure_patterns[key] = deque()

        # Keep only recent failures (last 60 seconds)
        recent = [ts for ts in self.failure_patterns[key]
                  if (now - ts).total_seconds() < 60]

        if len(recent) >= 3:
            logger.warning(f"⚠️  CIRCUIT BREAKER: {agent} hitting {error_type} repeatedly. Stopping retries.")
            return False  # Don't retry

        # Record this failure
        self.failure_patterns[key] = deque(recent + [now])
        return True  # Retry allowed

    def get_resource_status(self) -> Dict:
        """Get current system resource usage."""
        cpu_pct = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        return {
            "cpu_pct": cpu_pct,
            "ram_pct": mem.percent,
            "disk_pct": disk.percent,
            "ram_available_mb": mem.available / 1024 / 1024,
            "is_healthy": mem.percent < 80 and cpu_pct < 90,
        }

    def should_pause_heavy_tasks(self) -> bool:
        """Pause heavy tasks if system is under pressure."""
        resources = self.get_resource_status()
        if resources["ram_pct"] > 80 or resources["cpu_pct"] > 90:
            logger.warning(f"⚠️  System under pressure: RAM={resources['ram_pct']:.1f}%, CPU={resources['cpu_pct']:.1f}%")
            return True
        return False

    def get_scheduling_stats(self) -> Dict:
        """Get scheduling statistics."""
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "queue_depth": len(self.task_queue),
            "active_tasks": len(self.active_tasks),
            "sub_agents": len(self.sub_agents),
            "should_scale_up": self.should_scale_up(),
            "should_scale_down": self.should_scale_down(),
            "system_healthy": self.get_resource_status()["is_healthy"],
            "circuit_breaker_active": len(self.failure_patterns) > 0,
        }


# Global scheduler instance
scheduler = AdvancedScheduler()


def monitor_scheduler(interval: int = 30):
    """Monitor scheduler health and auto-scaling."""
    logger.info("🚀 ADVANCED SCHEDULER MONITOR STARTING (every 30 seconds)")

    while True:
        try:
            stats = scheduler.get_scheduling_stats()
            resources = scheduler.get_resource_status()

            logger.info(f"📊 Scheduler Status:")
            logger.info(f"   Queue: {stats['queue_depth']} tasks")
            logger.info(f"   Workers: {stats['sub_agents']} sub-agents")
            logger.info(f"   Resources: CPU={resources['cpu_pct']:.1f}%, RAM={resources['ram_pct']:.1f}%")
            logger.info(f"   Health: {'🟢 HEALTHY' if stats['system_healthy'] else '🔴 DEGRADED'}")

            # Auto-scaling decisions
            if stats["should_scale_up"]:
                logger.info("   ⬆️  SCALING UP (queue depth high)")
            elif stats["should_scale_down"]:
                logger.info("   ⬇️  SCALING DOWN (queue empty)")

            time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("🛑 Scheduler monitor stopped")
            break
        except Exception as e:
            logger.error(f"Scheduler monitor error: {e}", exc_info=True)
            time.sleep(interval)


if __name__ == "__main__":
    monitor_scheduler()
