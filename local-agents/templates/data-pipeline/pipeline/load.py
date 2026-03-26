"""Loading stage — writes transformed data to output."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .config import PipelineConfig

logger = logging.getLogger(__name__)


def load(df: pd.DataFrame, config: PipelineConfig) -> dict:
    """Write the transformed DataFrame to the configured output format.

    Supported output formats: parquet, csv, json.

    Args:
        df: Transformed DataFrame.
        config: Pipeline configuration.

    Returns:
        dict with keys: rows_written, output_path, format.
    """
    output_dir = Path(config.output_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / f"output.{config.output_format}"

    logger.info(
        "Loading %d rows to %s (format=%s)", len(df), output_file, config.output_format
    )

    if config.output_format == "parquet":
        df.to_parquet(output_file, index=False, compression="snappy")
    elif config.output_format == "csv":
        df.to_csv(output_file, index=False)
    elif config.output_format == "json":
        df.to_json(output_file, orient="records", lines=True)
    else:
        raise ValueError(f"Unsupported output format: {config.output_format!r}")

    result = {
        "rows_written": len(df),
        "output_path": str(output_file),
        "format": config.output_format,
    }
    logger.info("Load complete: %s", result)
    return result
