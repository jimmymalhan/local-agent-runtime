```python
# This script handles the clickable arrow routing feature for changing agent assignments in the UI.
# It updates projects.json with the new agent assignment and triggers live routing in the orchestrator.

import json

def update_agent_assignment(source_node, target_node):
    # Load current project data from projects.json
    with open('projects.json', 'r') as file:
        projects = json.load(file)
    
    # Update agent assignment for the source node to point to the target node
    projects[source_node]['agent'] = target_node
    
    # Save updated project data back to projects.json
    with open('projects.json', 'w') as file:
        json.dump(projects, file, indent=4)
    
    # Trigger live routing in the orchestrator (placeholder for actual routing logic)
    trigger_live_routing(source_node, target_node)

def trigger_live_routing(source_node, target_node):
    # Placeholder function to simulate triggering live routing
    print(f"Routing {source_node} to {target_node}")

# Example usage:
# update_agent_assignment('node1', 'node2')
```