"""Format-agnostic reader. Owner: A2. Contract + format inference; reader pending datasets."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mrf.contracts.models import Dataset, DatasetFormat

if TYPE_CHECKING:  # pandas is in the optional 'data' extra
    import pandas as pd

#: file suffix -> format; used when a dataset is registered without an explicit format.
SUFFIX_TO_FORMAT: dict[str, DatasetFormat] = {
    ".csv": DatasetFormat.CSV,
    ".txt": DatasetFormat.CSV,
    ".tsv": DatasetFormat.TSV,
    ".parquet": DatasetFormat.PARQUET,
    ".pq": DatasetFormat.PARQUET,
    ".feather": DatasetFormat.FEATHER,
    ".xlsx": DatasetFormat.XLSX,
    ".xls": DatasetFormat.XLS,
    ".jsonl": DatasetFormat.JSONL,
    ".json": DatasetFormat.JSON,
    ".sas7bdat": DatasetFormat.SAS7BDAT,
    ".xpt": DatasetFormat.XPT,
    ".rds": DatasetFormat.RDS,
    ".rdata": DatasetFormat.RDATA,
    ".rda": DatasetFormat.RDATA,
    ".sql": DatasetFormat.SQL,
}


def infer_format(uri: str) -> DatasetFormat:
    """Best-effort format from the uri suffix; unknown -> ``other`` (never raises)."""
    lower = uri.lower().split("?", 1)[0]
    for suffix, fmt in SUFFIX_TO_FORMAT.items():
        if lower.endswith(suffix):
            return fmt
    return DatasetFormat.OTHER


def read_any(dataset: Dataset, **overrides: Any) -> pd.DataFrame:
    """Read any registered dataset into a DataFrame (A2 implements).

    csv/tsv -> pandas.read_csv, parquet/feather -> pyarrow, xlsx/xls -> openpyxl,
    sas7bdat/xpt -> pyreadstat, rds/rdata -> pyreadr (optional), json/jsonl -> pandas.read_json.
    ``dataset.read_options`` + ``overrides`` are passed through to the reader.
    """
    raise NotImplementedError
