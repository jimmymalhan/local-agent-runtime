```python
# This script parses incoming messages for specific slash-commands and handles them accordingly before sending the rest of the message to an LLM.

def parse_command(message):
    if message.startswith('/status'):
        return 'live task counts'
    elif message.startswith('/agents'):
        return 'all agent states'
    elif message.startswith('/epics'):
        return 'pending epics + ETA'
    elif message.startswith('/why'):
        parts = message.split(' ', 1)
        if len(parts) > 1:
            task = parts[1]
            return f'failure reason for {task}'
    elif message.startswith('/help'):
        return 'available commands: /status, /agents, /epics, /why <task>, /help'
    
    # If no command is recognized, return the original message
    return message

# Example usage:
user_message = '/status'
response = parse_command(user_message)
print(response)  # Output: live task counts
```