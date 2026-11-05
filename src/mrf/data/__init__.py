"""Data loading + cleaning + schemas. Owner: A2.

``mrf.data.io.read_any`` reads any registered dataset into a pandas DataFrame.
``mrf.data.clean.clean`` applies a declarative cleaning spec. pandera schemas in
``mrf.data.schemas.SCHEMAS`` are the data-quality standard used by A4 monitoring.
"""
from mrf.data.clean import clean
from mrf.data.io import infer_format, read_any
from mrf.data.schemas import SCHEMAS, get_schema, validate

__all__ = [
    "read_any",
    "infer_format",
    "clean",
    "SCHEMAS",
    "get_schema",
    "validate",
]
