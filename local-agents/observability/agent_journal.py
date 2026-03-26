"""
agent_journal.py — Step-by-step journal of every agent decision.
Stored in local-agents/reports/journal/{task_id}.jsonl
"""
import json
from pathlib import Path
from datetime import datetime

JOURNAL_DIR = Path("local-agents/reports/journal")

class AgentJournal:
    def __init__(self, task_id: str, agent: str):
        self.task_id = task_id
        self.agent = agent
        self.step = 0
        self.file = JOURNAL_DIR / f"{task_id}.jsonl"
        JOURNAL_DIR.mkdir(parents=True, exist_ok=True)

    def log(self, action: str, reasoning: str = "", input_data=None, output_data=None,
            success: bool = True, tokens: int = 0):
        self.step += 1
        record = {
            "ts": datetime.utcnow().isoformat(),
            "step": self.step,
            "agent": self.agent,
            "action": action,
            "reasoning": reasoning[:200] if reasoning else "",
            "success": success,
            "tokens": tokens,
        }
        if input_data: record["input"] = str(input_data)[:200]
        if output_data: record["output"] = str(output_data)[:200]
        with open(self.file, "a") as f:
            f.write(json.dumps(record) + "\n")

    def read(self) -> list:
        if not self.file.exists(): return []
        with open(self.file) as f:
            return [json.loads(l) for l in f if l.strip()]
