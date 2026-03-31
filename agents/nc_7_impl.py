```python
# This script parses incoming messages for specific slash-commands and handles them accordingly before sending the rest of the message to an LLM.

def parse_slash_command(message):
    if message.startswith('/'):
        command = message.split()[0]
        args = message.split()[1:]
        
        if command == '/status':
            return handle_status()
        elif command == '/agents':
            return handle_agents()
        elif command == '/epics':
            return handle_epics()
        elif command.startswith('/why'):
            task = ' '.join(args)
            return handle_why(task)
        elif command == '/help':
            return handle_help()
        else:
            return None
    else:
        return message

def handle_status():
    # Implement logic to get live task counts
    return "Live task counts: [insert data]"

def handle_agents():
    # Implement logic to get all agent states
    return "Agent states: [insert data]"

def handle_epics():
    # Implement logic to get pending epics and ETA
    return "Pending epics with ETA: [insert data]"

def handle_why(task):
    # Implement logic to get failure reason for a specific task
    return f"Failure reason for '{task}': [insert data]"

def handle_help():
    # Implement logic to provide help information
    return "Available commands: /status, /agents, /epics, /why <task>, /help"
```