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
    import pandas as pd

    fmt = dataset.format or infer_format(dataset.uri)
    opts: dict[str, Any] = {**dataset.read_options, **overrides}

    if fmt == DatasetFormat.CSV:
        return pd.read_csv(dataset.uri, **opts)
    if fmt == DatasetFormat.TSV:
        return pd.read_csv(dataset.uri, sep="\t", **opts)
    if fmt == DatasetFormat.PARQUET:
        return pd.read_parquet(dataset.uri, **opts)
    if fmt == DatasetFormat.FEATHER:
        return pd.read_feather(dataset.uri, **opts)
    if fmt == DatasetFormat.XLSX:
        return pd.read_excel(dataset.uri, **opts)
    if fmt == DatasetFormat.XLS:
        return pd.read_excel(dataset.uri, **opts)
    if fmt == DatasetFormat.JSON:
        return pd.read_json(dataset.uri, **opts)
    if fmt == DatasetFormat.JSONL:
        return pd.read_json(dataset.uri, lines=True, **opts)
    if fmt in (DatasetFormat.SAS7BDAT, DatasetFormat.XPT):
        try:
            import pyreadstat  # type: ignore

            df, _ = pyreadstat.read_sas7bdat(dataset.uri) if fmt == DatasetFormat.SAS7BDAT else pyreadstat.read_xport(dataset.uri)
            return df
        except ImportError as exc:  # pragma: no cover - optional dep
            raise ImportError("pyreadstat is required for SAS/XPT; install the 'data' extra") from exc
    if fmt in (DatasetFormat.RDS, DatasetFormat.RDATA):
        raise NotImplementedError("R data files need pyreadr; not yet wired")

    raise ValueError(f"unsupported format: {fmt}")
