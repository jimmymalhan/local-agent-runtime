```python
# This file implements an epic header card with progress bars and ETAs for a local AI agent runtime.
from datetime import datetime, timedelta

class EpicHeaderCard:
    def __init__(self, title, completion_percentage, task_breakdown, estimated_completion_time, assigned_agents):
        self.title = title
        self.completion_percentage = completion_percentage
        self.task_breakdown = task_breakdown  # Dictionary with status as key and count as value
        self.estimated_completion_time = estimated_completion_time
        self.assigned_agents = assigned_agents

    def get_progress_bar(self):
        filled_length = int(50 * self.completion_percentage / 100)
        bar = '█' * filled_length + '-' * (50 - filled_length)
        return f"[{bar}] {self.completion_percentage}%"

    def get_task_breakdown_string(self):
        breakdown_str = ", ".join(f"{status}: {count}" for status, count in self.task_breakdown.items())
        return breakdown_str

    def get_eta_string(self):
        now = datetime.now()
        eta = now + timedelta(hours=self.estimated_completion_time)
        return f"ETA: {eta.strftime('%Y-%m-%d %H:%M')}"

    def get_assigned_agents_string(self):
        agents_str = ", ".join(assigned_agent.name for assigned_agent in self.assigned_agents)
        return f"Assigned Agents: {agents_str}"

    def display_card(self):
        print(f"Epic Title: {self.title}")
        print(self.get_progress_bar())
        print(f"Task Breakdown: {self.get_task_breakdown_string()}")
        print(self.get_eta_string())
        print(self.get_assigned_agents_string())

# Example usage:
class Agent:
    def __init__(self, name):
        self.name = name

agent1 = Agent("Agent A")
agent2 = Agent("Agent B")

epic_card = EpicHeaderCard(
    title="Project Alpha",
    completion_percentage=75,
    task_breakdown={"Completed": 3, "In Progress": 2, "Pending": 1},
    estimated_completion_time=48,
    assigned_agents=[agent1, agent2]
)

epic_card.display_card()
```