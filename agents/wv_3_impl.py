```python
# This script handles the logic for updating agent assignments based on user interactions in the UI.
# It reads from projects.json, updates the agent assignment, and sends the updated data to the orchestrator.

import json

def update_agent_assignment(source_node, target_node):
    # Load current project data from projects.json
    with open('projects.json', 'r') as file:
        projects = json.load(file)
    
    # Update the agent assignment for the source node
    if source_node in projects:
        projects[source_node]['agent'] = target_node
    
    # Save the updated project data back to projects.json
    with open('projects.json', 'w') as file:
        json.dump(projects, file, indent=4)
    
    # Send updated data to the orchestrator (placeholder for actual implementation)
    send_to_orchestrator(projects)

def send_to_orchestrator(updated_data):
    # Placeholder function to simulate sending data to the orchestrator
    print("Sending updated agent assignments to orchestrator:", updated_data)

# Example usage:
# update_agent_assignment('node1', 'node2')
```