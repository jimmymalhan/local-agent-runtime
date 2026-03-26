"""Pipeline configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PipelineConfig:
    """Central configuration for the {{name}} pipeline."""

    # Source
    source_path: str = os.environ.get("SOURCE_PATH", "data/raw")
    source_format: str = os.environ.get("SOURCE_FORMAT", "csv")

    # DuckDB
    database_path: str = os.environ.get("DATABASE_PATH", "data/pipeline.duckdb")

    # Output
    output_path: str = os.environ.get("OUTPUT_PATH", "data/processed")
    output_format: str = os.environ.get("OUTPUT_FORMAT", "parquet")

    # dbt
    dbt_project_dir: str = os.environ.get("DBT_PROJECT_DIR", "dbt")
    dbt_profiles_dir: str = os.environ.get("DBT_PROFILES_DIR", str(Path.home() / ".dbt"))
    dbt_target: str = os.environ.get("DBT_TARGET", "dev")

    # Execution
    batch_size: int = int(os.environ.get("BATCH_SIZE", "10000"))
    max_workers: int = int(os.environ.get("MAX_WORKERS", "4"))

    # Logging
    log_level: str = os.environ.get("LOG_LEVEL", "INFO")

    def validate(self) -> None:
        """Raise ValueError if configuration is invalid."""
        if not self.source_path:
            raise ValueError("SOURCE_PATH must be set")
        if self.batch_size < 1:
            raise ValueError("BATCH_SIZE must be >= 1")
        if self.max_workers < 1:
            raise ValueError("MAX_WORKERS must be >= 1")
