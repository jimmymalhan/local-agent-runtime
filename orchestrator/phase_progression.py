#!/usr/bin/env python3
"""
phase_progression.py — Automatic phase progression and task generation

When a phase completes, auto-generate the next phase's tasks.
This ensures continuous work stream without manual intervention.
"""

import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

PROJECTS_FILE = Path("projects.json")

# Phase templates - auto-generate these when phase completes
PHASE_TEMPLATES = {
    "phase_3": {
        "name": "Ultra Workflow Integration & Auto-Execution",
        "description": "Advanced workflow features and autonomous execution",
        "tasks": [
            {"id": "phase3-advanced-routing", "title": "Implement advanced task routing", "agent": "architect"},
            {"id": "phase3-concurrent-execution", "title": "Enable concurrent task execution", "agent": "executor"},
            {"id": "phase3-self-healing", "title": "Implement self-healing agent recovery", "agent": "debugger"},
            {"id": "phase3-quality-gates", "title": "Add quality gates to task execution", "agent": "reviewer"},
            {"id": "phase3-performance-tuning", "title": "Optimize execution performance", "agent": "benchmarker"},
        ]
    },
    "phase_4": {
        "name": "System Stability & Production Hardening",
        "description": "Final hardening for production deployment",
        "tasks": [
            {"id": "phase4-load-testing", "title": "Run load tests", "agent": "test_engineer"},
            {"id": "phase4-security-hardening", "title": "Implement security hardening", "agent": "researcher"},
            {"id": "phase4-documentation", "title": "Complete all documentation", "agent": "doc_writer"},
        ]
    }
}

def check_phase_completion(projects_data):
    """
    Check if any phase is complete and needs progression.
    
    Returns:
        List of completed phases that need progression
    """
    completed_phases = []
    
    for project in projects_data.get("projects", []):
        if project.get("status") == "completed":
            project_id = project.get("id", "")
            
            # Check if this is a phase project (has phase indicators)
            if any(x in project_id.lower() for x in ["phase", "production", "ultra", "system"]):
                completed_phases.append(project_id)
    
    return completed_phases


def generate_next_phase(phase_key, projects_data):
    """
    Generate tasks for the next phase.
    
    Args:
        phase_key: Which phase to generate (e.g., "phase_3")
        projects_data: Current projects.json data
    """
    if phase_key not in PHASE_TEMPLATES:
        logger.warning(f"Unknown phase template: {phase_key}")
        return False
    
    template = PHASE_TEMPLATES[phase_key]
    
    # Check if phase project already exists
    existing = any(p.get("id") == phase_key for p in projects_data.get("projects", []))
    if existing:
        logger.info(f"Phase {phase_key} already exists in projects.json")
        return False
    
    # Create phase project
    phase_project = {
        "id": phase_key,
        "name": template["name"],
        "description": template["description"],
        "status": "pending",
        "tasks": [
            {
                **task,
                "status": "pending",
                "priority": "P0",
                "files": [],
                "success_criteria": f"Complete: {task['title']}",
                "eta_hours": 4,
                "eta_completion": (datetime.utcnow().isoformat() + "Z"),
            }
            for task in template["tasks"]
        ],
        "eta_hours": 4 * len(template["tasks"]),
        "eta_completion": (datetime.utcnow().isoformat() + "Z"),
    }
    
    # Add to projects
    projects_data["projects"].append(phase_project)
    
    # Write updated projects.json
    try:
        with open(PROJECTS_FILE, "w") as f:
            json.dump(projects_data, f, indent=2)
        logger.info(f"✅ Generated {phase_key}: {len(template['tasks'])} tasks")
        return True
    except Exception as e:
        logger.error(f"Failed to write projects.json: {e}")
        return False


def auto_progress_phases():
    """
    Main function: check if phases completed and auto-generate next phases.
    """
    try:
        with open(PROJECTS_FILE) as f:
            projects_data = json.load(f)
        
        # Check which phases are complete
        completed = check_phase_completion(projects_data)
        
        if not completed:
            logger.debug("No phases complete yet")
            return
        
        logger.info(f"Completed phases: {completed}")
        
        # Auto-generate next phases in sequence
        if "production-upgrade" in completed or "production_upgrade" in completed:
            if generate_next_phase("phase_3", projects_data):
                # Reload data after modification
                with open(PROJECTS_FILE) as f:
                    projects_data = json.load(f)
        
        if "phase_3" in completed:
            if generate_next_phase("phase_4", projects_data):
                logger.info("✅ Phase progression complete: All phases generated")
        
    except Exception as e:
        logger.error(f"Phase progression failed: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    auto_progress_phases()
