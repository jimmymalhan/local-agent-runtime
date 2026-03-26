"""
error_patterns/ — Growing library of known errors and auto-fixes.

Grows automatically: every new unmatched error gets fingerprinted and added.
Hit rate metric tracked in state.json['error_pattern_stats'].
"""
from .library import ErrorPatternLibrary, get_library, auto_fix

__all__ = ["ErrorPatternLibrary", "get_library", "auto_fix"]
