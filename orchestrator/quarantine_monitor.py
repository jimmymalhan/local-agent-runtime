#!/usr/bin/env python3
"""
quarantine_monitor.py — Detect and fix macOS quarantine attributes

This module runs periodically to detect and remove com.apple.provenance attributes
that prevent Python files from executing with "Operation not permitted" errors.

This prevents the 7+ hour system blockage that occurred previously.
"""

import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def check_and_fix_quarantine(search_paths=None):
    """
    Scan for files with quarantine attributes and remove them.
    
    Args:
        search_paths: List of directories to scan (default: agents/, orchestrator/)
    
    Returns:
        dict with 'found' and 'fixed' counts
    """
    if search_paths is None:
        search_paths = [Path("agents"), Path("orchestrator"), Path("scripts"), Path(".claude")]
    
    result = {"found": 0, "fixed": 0, "errors": []}
    
    for search_path in search_paths:
        if not search_path.exists():
            continue
        
        for py_file in search_path.rglob("*.py"):
            try:
                # Check for quarantine attribute
                xattr_result = subprocess.run(
                    ["xattr", str(py_file)],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if "com.apple.provenance" in xattr_result.stdout:
                    result["found"] += 1
                    
                    # Try to remove it
                    fix_result = subprocess.run(
                        ["xattr", "-d", "com.apple.provenance", str(py_file)],
                        capture_output=True,
                        timeout=5
                    )
                    
                    if fix_result.returncode == 0:
                        result["fixed"] += 1
                        logger.warning(f"Fixed quarantine on {py_file}")
                    else:
                        result["errors"].append(str(py_file))
                        logger.error(f"Could not remove quarantine from {py_file}")
                        
            except Exception as e:
                logger.debug(f"Error checking {py_file}: {e}")
    
    return result


def report_quarantine_status():
    """
    Log quarantine status for monitoring.
    """
    result = check_and_fix_quarantine()
    
    if result["found"] > 0:
        logger.warning(
            f"QUARANTINE ALERT: Found {result['found']} files with quarantine attributes, "
            f"fixed {result['fixed']}, errors {len(result['errors'])}"
        )
        return False  # Problems found
    else:
        logger.info("Quarantine check passed - no issues detected")
        return True  # All clear


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    report_quarantine_status()
