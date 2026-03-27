"""
agent_implementations/ — Task implementation modules

Each module provides the actual code generation/implementation logic that agents call.
This design respects EXTREME CLAUDE SESSION RULES:
- Agents themselves (agents/*.py) remain unchanged
- Implementation logic is separated (agent_implementations/*.py)
- Agents can call into implementations without being edited

Architecture:
  agents/executor.py → agent_implementations/executor_impl.py
  agents/architect.py → agent_implementations/architect_impl.py
  etc.
"""

import json
from pathlib import Path
from typing import Dict, Any

BASE_DIR = Path(__file__).parent.parent

def parse_task_intent(task: Dict[str, Any]) -> str:
    """Extract implementation intent from task description."""
    title = task.get("title", "").lower()
    description = task.get("description", "").lower()
    combined = f"{title} {description}"
    return combined

def write_implementation_file(filename: str, content: str, subdir: str = ".") -> bool:
    """Write implementation file to the project."""
    filepath = BASE_DIR / subdir / filename
    filepath.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(filepath, "w") as f:
            f.write(content)
        return True
    except Exception as e:
        return False
