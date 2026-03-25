# datatools

A pip-installable Python package providing data transformation, validation, and statistics utilities.

## Installation

```bash
pip install -e ".[dev]"
```

## Modules

### `datatools.transform`
- `flatten(nested, depth=-1)` — recursively flatten nested lists/tuples
- `chunk(seq, size)` — split a list into fixed-size chunks
- `deduplicate(seq, key=None)` — remove duplicates preserving order

### `datatools.validate`
- `is_email(value)` — check if a string looks like a valid email
- `is_url(value)` — check if a string looks like a valid HTTP(S) URL
- `check_schema(data, schema)` — validate a dict against a simple type schema

### `datatools.stats`
- `mean(values)` — arithmetic mean
- `median(values)` — median value
- `stdev(values, population=False)` — standard deviation (sample or population)

## Running Tests

```bash
pytest
```

## License

MIT
