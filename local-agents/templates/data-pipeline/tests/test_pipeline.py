"""Tests for the {{name}} data pipeline."""
from __future__ import annotations

import os
import tempfile

import pandas as pd
import pytest

from pipeline.config import PipelineConfig
from pipeline.extract import extract_from_dataframe
from pipeline.transform import transform, apply_custom_transforms
from pipeline.load import load


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": [1, 2, 3],
            "Name": ["Alice", "Bob", "  Charlie  "],
            "Status": ["pending", "done", "pending"],
        }
    )


@pytest.fixture
def tmp_config(tmp_path) -> PipelineConfig:
    return PipelineConfig(
        source_path=str(tmp_path / "raw"),
        database_path=str(tmp_path / "test.duckdb"),
        output_path=str(tmp_path / "output"),
        output_format="csv",
    )


def test_config_validate_ok(tmp_config):
    tmp_config.validate()  # Should not raise


def test_config_validate_empty_source():
    config = PipelineConfig(source_path="")
    with pytest.raises(ValueError, match="SOURCE_PATH"):
        config.validate()


def test_extract_from_dataframe(sample_df, tmp_config):
    conn = extract_from_dataframe(sample_df, tmp_config)
    result = conn.execute("SELECT COUNT(*) FROM raw_data").fetchone()[0]
    assert result == 3


def test_transform_normalises_columns(sample_df, tmp_config):
    conn = extract_from_dataframe(sample_df, tmp_config)
    df = transform(conn, tmp_config)
    # Column names should be lowercase
    assert all(col == col.lower() for col in df.columns if col not in ("processed_at", "pipeline_version"))


def test_transform_adds_metadata(sample_df, tmp_config):
    conn = extract_from_dataframe(sample_df, tmp_config)
    df = transform(conn, tmp_config)
    assert "processed_at" in df.columns
    assert "pipeline_version" in df.columns


def test_apply_custom_transforms_strips_whitespace(sample_df, tmp_config):
    conn = extract_from_dataframe(sample_df, tmp_config)
    df = transform(conn, tmp_config)
    df = apply_custom_transforms(df)
    # "  Charlie  " should become "Charlie"
    name_col = [c for c in df.columns if "name" in c.lower()][0]
    assert "Charlie" in df[name_col].values


def test_load_csv(sample_df, tmp_config):
    conn = extract_from_dataframe(sample_df, tmp_config)
    df = transform(conn, tmp_config)
    result = load(df, tmp_config)
    assert result["rows_written"] == 3
    assert result["format"] == "csv"
    import os
    assert os.path.exists(result["output_path"])


def test_load_parquet(sample_df, tmp_config):
    tmp_config.output_format = "parquet"
    conn = extract_from_dataframe(sample_df, tmp_config)
    df = transform(conn, tmp_config)
    result = load(df, tmp_config)
    assert result["format"] == "parquet"
    assert result["rows_written"] == 3


def test_load_invalid_format(sample_df, tmp_config):
    tmp_config.output_format = "xml"
    conn = extract_from_dataframe(sample_df, tmp_config)
    df = transform(conn, tmp_config)
    with pytest.raises(ValueError, match="Unsupported output format"):
        load(df, tmp_config)
