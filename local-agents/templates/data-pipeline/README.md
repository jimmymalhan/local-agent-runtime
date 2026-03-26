# {{name}}

Data pipeline with DuckDB, Pandas, and dbt.

## Quick start

```bash
pip install -r requirements.txt
python -m pipeline.run
```

## Run dbt models

```bash
cd dbt
dbt run
dbt test
```

## Tests

```bash
pytest -v
```

## Pipeline stages

| Stage | File | Description |
|---|---|---|
| Extract | `pipeline/extract.py` | Reads CSV/Parquet/JSON into DuckDB |
| Transform | `pipeline/transform.py` | Normalises columns, filters nulls |
| Load | `pipeline/load.py` | Writes Parquet/CSV/JSON output |

## Configuration

All settings are environment variables with sensible defaults:

| Variable | Default | Description |
|---|---|---|
| `SOURCE_PATH` | `data/raw` | Input data directory |
| `SOURCE_FORMAT` | `csv` | csv / parquet / json |
| `DATABASE_PATH` | `data/pipeline.duckdb` | DuckDB file |
| `OUTPUT_PATH` | `data/processed` | Output directory |
| `OUTPUT_FORMAT` | `parquet` | parquet / csv / json |
| `BATCH_SIZE` | `10000` | Rows per batch |

## dbt models

```
dbt/models/
  staging/stg_items.sql         # Clean and rename raw data
  marts/mart_items_summary.sql  # Aggregated summary table
```
