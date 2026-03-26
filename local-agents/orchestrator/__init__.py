"""orchestrator package — exposes key components for external imports."""
try:
    from orchestrator.continuous_loop import ContinuousLoop  # noqa: F401
except ImportError:
    pass
