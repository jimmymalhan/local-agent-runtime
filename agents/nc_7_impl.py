```python
# This script parses incoming messages for specific slash-commands and handles them accordingly before sending the rest of the message to the LLM.

def parse_command(message):
    if message.startswith('/status'):
        return handle_status()
    elif message.startswith('/agents'):
        return handle_agents()
    elif message.startswith('/epics'):
        return handle_epics()
    elif message.startswith('/why'):
        parts = message.split(' ', 1)
        if len(parts) > 1:
            task = parts[1]
            return handle_why(task)
    elif message.startswith('/help'):
        return handle_help()
    else:
        return None

def handle_status():
    # Implement logic to get live task counts
    return "Live task counts: [insert count]"

def handle_agents():
    # Implement logic to get all agent states
    return "Agent states: [insert states]"

def handle_epics():
    # Implement logic to get pending epics and ETA
    return "Pending epics with ETA: [insert details]"

def handle_why(task):
    # Implement logic to get failure reason for a specific task
    return f"Failure reason for {task}: [insert reason]"

def handle_help():
    # Implement logic to provide help information
    return "Available commands: /status, /agents, /epics, /why <task>, /help"
```