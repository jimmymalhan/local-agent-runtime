```python
# This file implements an epic header card with progress bars and ETAs for a local AI agent runtime.
from datetime import datetime, timedelta

class EpicCard:
    def __init__(self, title, total_tasks, completed_tasks, assigned_agents):
        self.title = title
        self.total_tasks = total_tasks
        self.completed_tasks = completed_tasks
        self.assigned_agents = assigned_agents
        self.start_time = datetime.now()

    @property
    def completion_percentage(self):
        return (self.completed_tasks / self.total_tasks) * 100 if self.total_tasks > 0 else 0

    @property
    def estimated_completion_time(self):
        elapsed_time = datetime.now() - self.start_time
        average_task_duration = elapsed_time / self.completed_tasks if self.completed_tasks > 0 else timedelta(0)
        remaining_tasks = self.total_tasks - self.completed_tasks
        return self.start_time + (average_task_duration * remaining_tasks)

    @property
    def task_breakdown(self):
        completed = [task for task in self.assigned_agents if task['status'] == 'completed']
        in_progress = [task for task in self.assigned_agents if task['status'] == 'in_progress']
        pending = [task for task in self.assigned_agents if task['status'] == 'pending']
        return {
            'completed': len(completed),
            'in_progress': len(in_progress),
            'pending': len(pending)
        }

    def velocity_sparkline(self):
        # Simplified sparkline generation
        days = [self.start_time + timedelta(days=i) for i in range(7)]
        velocities = [(i+1) * 20 for i in range(7)]  # Example velocity data
        return {day: vel for day, vel in zip(days, velocities)}

    def display(self):
        print(f"Title: {self.title}")
        print(f"Completion %: {self.completion_percentage:.2f}%")
        print(f"Task Breakdown: {self.task_breakdown}")
        print(f"Estimated Completion Time: {self.estimated_completion_time.strftime('%Y-%m-%d %H:%M')}")
        print("Velocity Sparkline:")
        for day, vel in self.velocity_sparkline().items():
            print(f"{day.strftime('%Y-%m-%d')} - Velocity: {vel}")

# Example usage:
epic = EpicCard(
    title="Project Alpha",
    total_tasks=10,
    completed_tasks=3,
    assigned_agents=[
        {'name': 'Agent 1', 'status': 'completed'},
        {'name': 'Agent 2', 'status': 'in_progress'},
        {'name': 'Agent 3', 'status': 'pending'}
    ]
)
epic.display()
```