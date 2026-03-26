"""Extraction stage — reads raw data into DuckDB."""
from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pandas as pd

from .config import PipelineConfig

logger = logging.getLogger(__name__)


def extract(config: PipelineConfig) -> duckdb.DuckDBPyConnection:
    """Read source files into DuckDB and return a connection.

    Supports CSV, Parquet, and JSON source formats.

    Args:
        config: Pipeline configuration.

    Returns:
        DuckDB connection with `raw_data` table populated.
    """
    source = Path(config.source_path)
    conn = duckdb.connect(config.database_path)

    logger.info("Extracting data from %s (format=%s)", source, config.source_format)

    if config.source_format == "csv":
        glob_pattern = str(source / "*.csv")
        conn.execute(f"""
            CREATE OR REPLACE TABLE raw_data AS
            SELECT * FROM read_csv_auto('{glob_pattern}', union_by_name=true)
        """)
    elif config.source_format == "parquet":
        glob_pattern = str(source / "*.parquet")
        conn.execute(f"""
            CREATE OR REPLACE TABLE raw_data AS
            SELECT * FROM read_parquet('{glob_pattern}', union_by_name=true)
        """)
    elif config.source_format == "json":
        glob_pattern = str(source / "*.json")
        conn.execute(f"""
            CREATE OR REPLACE TABLE raw_data AS
            SELECT * FROM read_json_auto('{glob_pattern}')
        """)
    else:
        raise ValueError(f"Unsupported source format: {config.source_format!r}")

    row_count = conn.execute("SELECT COUNT(*) FROM raw_data").fetchone()[0]
    logger.info("Extracted %d rows into raw_data", row_count)

    return conn


def extract_from_dataframe(df: pd.DataFrame, config: PipelineConfig) -> duckdb.DuckDBPyConnection:
    """Load a DataFrame directly into DuckDB (useful for testing).

    Args:
        df: Source DataFrame.
        config: Pipeline configuration.

    Returns:
        DuckDB connection with `raw_data` table populated.
    """
    conn = duckdb.connect(config.database_path)
    conn.execute("CREATE OR REPLACE TABLE raw_data AS SELECT * FROM df")
    logger.info("Loaded %d rows from DataFrame", len(df))
    return conn
