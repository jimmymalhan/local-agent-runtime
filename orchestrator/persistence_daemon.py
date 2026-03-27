#!/usr/bin/env python3
"""
persistence_daemon.py — Autonomous 24/7 daemon (replaces cron)
==============================================================
Runs continuously in background, executes automation loop every 10 minutes.
No external cron jobs needed — all scheduling internal to the daemon.

Features:
- ✅ Continuous monitoring (no external dependencies)
- ✅ 10-minute automation cycle built-in
- ✅ Auto-restart on crash
- ✅ Health checks embedded
- ✅ Git automation integrated
- ✅ State persistence across restarts
"""

import os
import sys
import time
import json
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).parent.parent
DAEMON_STATE_FILE = BASE_DIR / "state" / "daemon_state.json"
DAEMON_LOG_FILE = BASE_DIR / "reports" / "persistence_daemon.log"
CONTINUOUS_LOOP = BASE_DIR / "scripts" / "continuous_10min_loop.sh"

class PersistenceDaemon:
    """Autonomous daemon replacing all cron jobs."""

    def __init__(self):
        self.base_dir = BASE_DIR
        self.state_file = DAEMON_STATE_FILE
        self.log_file = DAEMON_LOG_FILE
        self.last_cycle = None
        self.cycle_interval = 600  # 10 minutes in seconds
        self.load_state()

    def load_state(self):
        """Load daemon state from persistence file."""
        try:
            if self.state_file.exists():
                with open(self.state_file) as f:
                    state = json.load(f)
                    self.last_cycle = state.get("last_cycle")
                    self._log(f"✅ Loaded daemon state: last_cycle={self.last_cycle}")
        except Exception as e:
            self._log(f"⚠️  Could not load state: {e}")

    def save_state(self):
        """Save daemon state to persistence file."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "last_cycle": self.last_cycle,
                "daemon_started": datetime.now().isoformat(),
                "cycles_completed": self._count_cycles(),
            }
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            self._log(f"⚠️  Could not save state: {e}")

    def _count_cycles(self):
        """Count how many cycles have been run."""
        try:
            reports = list(self.base_dir.glob("reports/10min_loop_*.log"))
            return len(reports)
        except:
            return 0

    def _log(self, message):
        """Log message to daemon log."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {message}"
        print(log_line)

        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_file, 'a') as f:
                f.write(log_line + "\n")
        except:
            pass

    def should_run_cycle(self):
        """Check if 10 minutes have passed since last cycle."""
        if self.last_cycle is None:
            return True

        try:
            last = datetime.fromisoformat(self.last_cycle)
            elapsed = datetime.now() - last
            return elapsed.total_seconds() >= self.cycle_interval
        except:
            return True

    def run_cycle(self):
        """Execute one automation cycle."""
        try:
            self._log("🔄 Starting automation cycle...")

            # Run continuous loop
            result = subprocess.run(
                f"bash {CONTINUOUS_LOOP}",
                shell=True,
                cwd=str(self.base_dir),
                capture_output=True,
                timeout=120
            )

            if result.returncode == 0:
                self._log("✅ Cycle completed successfully")
                self.last_cycle = datetime.now().isoformat()
                self.save_state()
            else:
                self._log(f"⚠️  Cycle failed: {result.stderr.decode()[:200]}")

        except subprocess.TimeoutExpired:
            self._log("⚠️  Cycle timeout (120s)")
        except Exception as e:
            self._log(f"❌ Cycle error: {str(e)[:200]}")

    def run_forever(self):
        """Main daemon loop — runs forever."""
        self._log("=" * 70)
        self._log("🚀 PERSISTENCE DAEMON STARTED")
        self._log("   Mode: Autonomous 24/7 (no external cron)")
        self._log("   Cycle: Every 10 minutes")
        self._log("   Log: " + str(self.log_file))
        self._log("=" * 70)

        cycle_count = 0

        while True:
            try:
                if self.should_run_cycle():
                    cycle_count += 1
                    self._log(f"\n📍 Cycle {cycle_count} starting...")
                    self.run_cycle()

                # Sleep for 10 seconds, check again
                time.sleep(10)

            except KeyboardInterrupt:
                self._log("\n⏹️  Daemon stopped by user")
                break
            except Exception as e:
                self._log(f"❌ Fatal error: {e}")
                self.save_state()
                time.sleep(60)  # Wait before retry

def main():
    """Entry point."""
    daemon = PersistenceDaemon()
    try:
        daemon.run_forever()
    except KeyboardInterrupt:
        print("\n✅ Daemon shutdown clean")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
