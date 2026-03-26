"""Transformation stage — applies business logic to raw data."""
from __future__ import annotations

import logging

import duckdb
import pandas as pd

from .config import PipelineConfig

logger = logging.getLogger(__name__)


def transform(conn: duckdb.DuckDBPyConnection, config: PipelineConfig) -> pd.DataFrame:
    """Apply transformations to raw_data and return a clean DataFrame.

    Transformations applied:
    - Drop rows where all values are NULL
    - Normalize column names (lowercase, underscores)
    - Add pipeline metadata columns (processed_at, pipeline_version)

    Args:
        conn: DuckDB connection with `raw_data` table.
        config: Pipeline configuration.

    Returns:
        Transformed DataFrame ready for loading.
    """
    logger.info("Transforming raw_data")

    # Normalise column names
    columns = conn.execute("DESCRIBE raw_data").df()["column_name"].tolist()
    renamed = {col: col.lower().replace(" ", "_").replace("-", "_") for col in columns}
    rename_sql = ", ".join(f'"{old}" AS "{new}"' for old, new in renamed.items())

    conn.execute(f"""
        CREATE OR REPLACE TABLE transformed AS
        SELECT
            {rename_sql},
            current_timestamp AS processed_at,
            '0.1.0' AS pipeline_version
        FROM raw_data
        WHERE NOT (
            {" AND ".join(f'"{col}" IS NULL' for col in columns)}
        )
    """)

    df = conn.execute("SELECT * FROM transformed").df()
    logger.info("Transformation complete: %d rows, %d columns", len(df), len(df.columns))
    return df


def apply_custom_transforms(df: pd.DataFrame) -> pd.DataFrame:
    """Hook for project-specific transformations.

    Override or extend this function to add domain logic.

    Args:
        df: Input DataFrame.

    Returns:
        Transformed DataFrame.
    """
    # Example: strip whitespace from string columns
    str_cols = df.select_dtypes(include="object").columns
    df[str_cols] = df[str_cols].apply(lambda c: c.str.strip())
    return df
