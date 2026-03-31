```python
# This script provides functionality to export a workflow as a JSON blob and import it to restore pipelines.

import json
from typing import Dict

def export_workflow_as_json(workflow: Dict) -> str:
    """
    Export the current workflow graph as a JSON string.
    
    Args:
        workflow (Dict): The workflow dictionary containing the graph data.
        
    Returns:
        str: A JSON string representing the workflow.
    """
    return json.dumps(workflow, indent=4)

def import_workflow_from_json(json_string: str) -> Dict:
    """
    Import a workflow from a JSON string and restore it as a pipeline.
    
    Args:
        json_string (str): The JSON string representing the workflow.
        
    Returns:
        Dict: A dictionary containing the restored workflow graph.
    """
    return json.loads(json_string)
```