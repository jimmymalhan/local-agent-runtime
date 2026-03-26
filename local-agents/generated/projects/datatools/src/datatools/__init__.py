"""datatools — data transformation, validation, and statistics utilities."""

__version__ = "0.1.0"

from datatools.transform import flatten, chunk, deduplicate
from datatools.validate import is_email, is_url, check_schema
from datatools.stats import mean, median, stdev

__all__ = [
    "flatten",
    "chunk",
    "deduplicate",
    "is_email",
    "is_url",
    "check_schema",
    "mean",
    "median",
    "stdev",
]
