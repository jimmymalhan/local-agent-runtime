```python
# This script provides functionality to export a workflow as a JSON blob and import it to restore pipelines.

import json
import requests

def export_workflow_as_json(workflow_id):
    """
    Export the current workflow graph as a JSON blob.
    
    Args:
    workflow_id (str): The ID of the workflow to export.
    
    Returns:
    str: The JSON representation of the workflow.
    """
    # Simulate fetching the workflow data from an API
    url = f"https://api.example.com/workflows/{workflow_id}"
    response = requests.get(url)
    if response.status_code == 200:
        return json.dumps(response.json(), indent=4)
    else:
        raise Exception(f"Failed to export workflow: {response.status_code}")

def import_workflow_from_json(json_data):
    """
    Import a workflow from a JSON blob.
    
    Args:
    json_data (str): The JSON representation of the workflow.
    
    Returns:
    str: Confirmation message.
    """
    # Simulate uploading the workflow data to an API
    url = "https://api.example.com/workflows"
    headers = {'Content-Type': 'application/json'}
    response = requests.post(url, data=json_data, headers=headers)
    if response.status_code == 201:
        return "Workflow imported successfully."
    else:
        raise Exception(f"Failed to import workflow: {response.status_code}")

# Example usage
workflow_id = "example_workflow_123"
json_blob = export_workflow_as_json(workflow_id)
print("Exported JSON:", json_blob)

import_result = import_workflow_from_json(json_blob)
print(import_result)
```