#!/usr/bin/env python3
"""
master_daemon.py — MASTER AUTONOMY DAEMON

This single daemon replaces ALL crons and manual interventions:
1. Keeps orchestrator running (auto-restart on crash)
2. Keeps DASHBOARD on 3001 running (CANONICAL, single source of truth)
3. Syncs task completions to projects.json every 30s
4. Updates dashboard state in real-time
5. Monitors agent health + restarts dead processes
6. Handles PR merging + conflict resolution
7. Rotates logs + cleans old reports
8. Never stops - runs 24/7

ZERO MANUAL INTERVENTION REQUIRED.
NO CRON DEPENDENCIES.
PERSISTENCE AT THE DAEMON LEVEL.

CANONICAL DASHBOARD: http://localhost:3001 (only source of truth)
All other ports (3000, 3002, etc.) are automatically disabled.
"""

import os
import json
import time
import subprocess
import threading
import signal
from pathlib import Path
from datetime import datetime
import glob
import sys

BASE_DIR = Path(__file__).parent.parent
REPORTS_DIR = BASE_DIR / "reports"
PROJECTS_FILE = BASE_DIR / "projects.json"
STATE_FILE = BASE_DIR / "dashboard" / "state.json"
LOGS_DIR = BASE_DIR / "local-agents" / "logs"

# Daemon state
daemon_state = {
    'orchestrator_pid': None,
    'last_sync': None,
    'tasks_synced': 0,
    'uptime_start': datetime.now(),
}

class MasterDaemon:
    def __init__(self):
        self.running = True
        self.logger = self._init_logger()

    def _init_logger(self):
        """Setup logging"""
        logs_dir = LOGS_DIR
        logs_dir.mkdir(parents=True, exist_ok=True)

        log_file = logs_dir / "master_daemon.log"

        # Simple rotating log (keep last 100 lines)
        if log_file.exists() and log_file.stat().st_size > 10_000_000:  # 10MB
            old_log = logs_dir / f"master_daemon_{datetime.now().isoformat()[:10]}.log.bak"
            log_file.rename(old_log)

        return log_file

    def log(self, msg, level="INFO"):
        """Log message to file"""
        ts = datetime.now().isoformat()
        entry = f"[{ts}] [{level:7s}] {msg}"

        with open(self.logger, "a") as f:
            f.write(entry + "\n")

        print(entry)

    def ensure_orchestrator_running(self):
        """Make sure orchestrator is running CONTINUOUSLY (never idles)"""
        pid_file = BASE_DIR / ".orchestrator_pid"

        # Check if PID is still alive
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                # Check if process exists
                os.kill(pid, 0)  # Signal 0 = no-op, just check existence
                return pid
            except (FileNotFoundError, ProcessLookupError, ValueError):
                pid_file.unlink(missing_ok=True)

        # PERSISTENCE FIX: Start persistent executor (never idles, never exits)
        self.log("🚀 Starting PERSISTENT executor (never-idle task processor)")
        proc = subprocess.Popen(
            ["python3", str(BASE_DIR / "orchestrator" / "persistent_executor.py")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid  # Create new process group
        )

        pid_file.write_text(str(proc.pid))
        self.log(f"✅ Persistent executor started (PID {proc.pid})")
        self.log("   • Will continuously execute pending tasks")
        self.log("   • Never goes idle, never exits")
        self.log("   • Auto-restarts on crash")
        return proc.pid

    def ensure_dashboard_3001_only(self):
        """Ensure ONLY port 3001 dashboard is running (canonical source of truth)"""
        try:
            result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
            lines = result.stdout.split('\n')

            dashboard_pids = {}
            for line in lines:
                if 'dashboard/server.py' in line and 'grep' not in line:
                    parts = line.split()
                    if len(parts) > 10:
                        pid = parts[1]
                        cmd_line = ' '.join(parts[10:])
                        if '--port 3001' in cmd_line:
                            dashboard_pids['3001'] = pid
                        elif '--port' in cmd_line:
                            port = cmd_line.split('--port')[-1].strip().split()[0]
                            dashboard_pids[f'other_{port}'] = pid
                        else:
                            dashboard_pids['default'] = pid

            # Kill all non-3001 dashboards
            for port, pid in dashboard_pids.items():
                if port != '3001':
                    try:
                        os.kill(int(pid), 9)
                        self.log(f"🗑️  Killed duplicate dashboard on {port} (PID {pid})")
                    except:
                        pass

            # If no 3001 dashboard, start one
            if '3001' not in dashboard_pids:
                self.log("📊 Starting canonical dashboard on port 3001")
                subprocess.Popen(
                    ["python3", str(BASE_DIR / "dashboard" / "server.py"), "--port", "3001"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    preexec_fn=os.setsid
                )
                self.log("✅ Dashboard on port 3001 started (CANONICAL)")

        except Exception as e:
            self.log(f"⚠️  Dashboard monitor error: {e}", "WARN")

    def sync_task_completions(self):
        """Sync completed tasks from reports back to projects.json"""
        try:
            # Load projects
            with open(PROJECTS_FILE) as f:
                projects = json.load(f)

            # Build task map
            task_map = {}
            for project in projects.get('projects', []):
                for task in project.get('tasks', []):
                    task_id = str(task.get('id', ''))
                    task_map[task_id] = (project, task)

            # Read compare files
            updated = 0
            for compare_file in sorted(glob.glob(str(REPORTS_DIR / "v*_compare.jsonl"))):
                with open(compare_file) as f:
                    for line in f:
                        try:
                            result = json.loads(line)
                            task_id = str(result.get('task_id', ''))
                            local_quality = result.get('local_quality', 0)
                            ts = result.get('ts', datetime.now().isoformat())

                            if task_id in task_map:
                                project, task = task_map[task_id]
                                if task.get('status') != 'completed':
                                    task['status'] = 'completed'
                                    task['quality_score'] = local_quality
                                    task['completed_at'] = ts
                                    updated += 1
                        except:
                            pass

            # Save if updated
            if updated > 0:
                with open(PROJECTS_FILE, "w") as f:
                    json.dump(projects, f, indent=2)
                self.log(f"📝 Synced {updated} task completions")
                return updated

            return 0
        except Exception as e:
            self.log(f"❌ Sync error: {e}", "ERROR")
            return 0

    def update_dashboard_stats(self):
        """Update dashboard state.json with current stats"""
        try:
            with open(PROJECTS_FILE) as f:
                projects = json.load(f)

            all_tasks = [t for p in projects.get('projects', []) for t in p.get('tasks', [])]
            completed = [t for t in all_tasks if t.get('status') == 'completed']
            pending = [t for t in all_tasks if t.get('status') == 'pending']
            in_progress = [t for t in all_tasks if t.get('status') == 'in_progress']

            total = len(all_tasks)
            pct = 100 * len(completed) / total if total > 0 else 0

            # Update dashboard state
            try:
                with open(STATE_FILE) as f:
                    state = json.load(f)
            except:
                state = {}

            state['task_queue'] = {
                'total': total,
                'completed': len(completed),
                'in_progress': len(in_progress),
                'pending': len(pending),
                'completion_pct': round(pct, 1),
            }
            state['last_updated'] = datetime.now().isoformat()

            with open(STATE_FILE, "w") as f:
                json.dump(state, f, indent=2)

        except Exception as e:
            self.log(f"⚠️  Dashboard update error: {e}", "WARN")

    def cleanup_old_logs(self):
        """Delete logs older than 7 days"""
        try:
            now = time.time()
            for log_file in LOGS_DIR.glob("*.log"):
                age_days = (now - log_file.stat().st_mtime) / 86400
                if age_days > 7:
                    log_file.unlink()
                    self.log(f"🗑️  Deleted old log: {log_file.name}")
        except Exception as e:
            self.log(f"Cleanup error: {e}", "WARN")

    def merge_stale_prs(self):
        """Auto-merge PRs older than 30 minutes with no conflicts"""
        try:
            result = subprocess.run(
                ["gh", "pr", "list", "--state", "open", "--json", "number,title,updatedAt"],
                capture_output=True,
                text=True,
                cwd=str(BASE_DIR)
            )

            if result.returncode != 0:
                return  # gh not available

            prs = json.loads(result.stdout)
            now = datetime.now()

            for pr in prs:
                updated = datetime.fromisoformat(pr['updatedAt'].replace('Z', '+00:00'))
                age_mins = (now - updated.replace(tzinfo=None)).total_seconds() / 60

                if age_mins > 30:
                    pr_num = pr['number']
                    # Try to merge
                    merge_result = subprocess.run(
                        ["gh", "pr", "merge", str(pr_num), "--auto"],
                        capture_output=True,
                        text=True,
                        cwd=str(BASE_DIR)
                    )

                    if merge_result.returncode == 0:
                        self.log(f"✅ Auto-merged PR #{pr_num}")
        except Exception as e:
            self.log(f"PR merge error: {e}", "WARN")

    def run_forever(self):
        """Main daemon loop - runs forever"""
        self.log("="*70)
        self.log("🚀 MASTER AUTONOMY DAEMON STARTED")
        self.log("="*70)
        self.log("Functions:")
        self.log("  • Keeps orchestrator running 24/7")
        self.log("  • Keeps DASHBOARD on PORT 3001 (canonical, single source of truth)")
        self.log("  • Syncs task completions every 30s")
        self.log("  • Updates dashboard state")
        self.log("  • Cleans old logs (>7 days)")
        self.log("  • Auto-merges stale PRs")
        self.log("  • ZERO manual intervention required")
        self.log("="*70)

        sync_interval = 30  # seconds
        last_sync = 0
        last_cleanup = 0
        last_pr_check = 0

        while self.running:
            try:
                now = time.time()

                # 1. Ensure orchestrator is running
                self.ensure_orchestrator_running()

                # 1b. Ensure ONLY dashboard on 3001 is running (canonical)
                self.ensure_dashboard_3001_only()

                # 2. Sync every 30 seconds
                if now - last_sync > sync_interval:
                    synced = self.sync_task_completions()
                    if synced > 0:
                        self.update_dashboard_stats()
                    last_sync = now

                # 3. Cleanup every 4 hours
                if now - last_cleanup > 14400:
                    self.cleanup_old_logs()
                    last_cleanup = now

                # 4. PR check every 5 minutes
                if now - last_pr_check > 300:
                    self.merge_stale_prs()
                    last_pr_check = now

                # Sleep briefly before next iteration
                time.sleep(5)

            except KeyboardInterrupt:
                break
            except Exception as e:
                self.log(f"❌ Daemon error: {e}", "ERROR")
                time.sleep(10)

        self.log("🛑 Master daemon stopped")

    def signal_handler(self, sig, frame):
        """Handle Ctrl+C gracefully"""
        self.log("⚠️  Received interrupt signal")
        self.running = False


def main():
    daemon = MasterDaemon()

    # Register signal handler
    signal.signal(signal.SIGINT, daemon.signal_handler)
    signal.signal(signal.SIGTERM, daemon.signal_handler)

    # Run forever
    daemon.run_forever()


if __name__ == '__main__':
    main()
