"""Pipeline orchestrator — runs extract → transform → load."""
from __future__ import annotations

import logging
import time

from .config import PipelineConfig
from .extract import extract
from .transform import transform, apply_custom_transforms
from .load import load

logger = logging.getLogger(__name__)


def run_pipeline(config: PipelineConfig | None = None) -> dict:
    """Execute the full ETL pipeline.

    Args:
        config: Pipeline configuration. Uses defaults if None.

    Returns:
        dict with pipeline run statistics.
    """
    if config is None:
        config = PipelineConfig()

    config.validate()

    logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Starting {{name}} pipeline")

    start = time.perf_counter()

    conn = extract(config)
    df = transform(conn, config)
    df = apply_custom_transforms(df)
    result = load(df, config)

    elapsed = round(time.perf_counter() - start, 2)
    stats = {**result, "duration_seconds": elapsed}

    logger.info("Pipeline complete in %.2fs: %s", elapsed, stats)
    return stats


if __name__ == "__main__":
    run_pipeline()
