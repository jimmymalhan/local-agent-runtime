#!/usr/bin/env python3
"""persistence_layer.py — Persist task state across restarts"""
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"

class PersistenceLayer:
    def __init__(self):
        self.queue_file = STATE_DIR / "task_queue.json"
        self.agent_state_file = STATE_DIR / "agent_state.json"

    def load_queue(self):
        """Load persistent task queue."""
        if self.queue_file.exists():
            with open(self.queue_file) as f:
                return json.load(f)
        return {"tasks": [], "last_updated": None}

    def save_queue(self, queue):
        """Save task queue to persistent storage."""
        self.queue_file.write_text(json.dumps(queue, indent=2))

    def load_agent_state(self):
        """Load persistent agent state."""
        if self.agent_state_file.exists():
            with open(self.agent_state_file) as f:
                return json.load(f)
        return {}

    def save_agent_state(self, state):
        """Save agent state to persistent storage."""
        self.agent_state_file.write_text(json.dumps(state, indent=2))

if __name__ == "__main__":
    pl = PersistenceLayer()
    queue = pl.load_queue()
    print(f"Loaded {len(queue.get('tasks', []))} tasks from persistent storage")
