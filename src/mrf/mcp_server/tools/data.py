"""Owner: A2."""

from __future__ import annotations

from typing import Any

import numpy as np

from mrf.contracts.models import Dataset
from mrf.core import MRFCode, MRFError
from mrf.monitoring.frames import load_frame
from mrf.storage import Collections, get_repo


async def profile_data(dataset_id: str, columns: list[str] | None = None, max_top_values: int = 5) -> dict[str, Any]:
    """Profile a registered dataset of any supported format (csv, parquet, xlsx, sas7bdat, rds...).

    Returns:
        {"dataset_id": str, "row_count": int, "format": str,
         "columns": [{"name": str, "dtype": str, "missing_rate": float, "n_unique": int,
                      "min": float | None, "max": float | None, "mean": float | None,
                      "top_values": [[value, count]]}],
         "warnings": [str]}
    Never returns raw rows (privacy rule). Raises MRF-1404 / MRF-1003.
    """
    from pandas.api.types import is_bool_dtype, is_numeric_dtype

    repo = get_repo()
    dataset = await repo.get(Collections.DATASETS, dataset_id, Dataset)  # missing -> MRF-1404

    try:
        df = load_frame(dataset)
    except (ValueError, ImportError) as exc:
        raise MRFError(
            MRFCode.INPUT_FILE_TYPE, f"dataset '{dataset_id}' could not be read: {exc}", field="dataset_id"
        ) from exc

    # Narrow to requested columns (validate they exist -> MRF-1003).
    if columns:
        missing = [c for c in columns if c not in df.columns]
        if missing:
            raise MRFError(
                MRFCode.INPUT_DATA_SCHEMA,
                f"unknown columns: {missing}",
                field="columns",
                detail={"dataset_id": dataset_id},
            )
        df = df[columns]

    warnings: list[str] = []
    if df.shape[0] == 0:
        warnings.append("dataset has 0 rows")

    profiles: list[dict[str, Any]] = []
    for name in df.columns:
        series = df[name]
        n = len(series)
        missing_rate = round(int(series.isna().sum()) / n, 6) if n else 0.0

        # numeric stats only for numeric columns; None otherwise
        min_v: float | None = None
        max_v: float | None = None
        mean_v: float | None = None
        if is_numeric_dtype(series) and not is_bool_dtype(series):  # np.issubdtype rejects pandas string dtypes
            min_v = _finite_or_none(series.min())
            max_v = _finite_or_none(series.max())
            mean_v = _finite_or_none(series.mean())

        # top values (drop NaN; value -> count, most frequent first)
        top_values = [[_jsonable(v), int(c)] for v, c in series.dropna().value_counts().head(max_top_values).items()]

        profiles.append(
            {
                "name": str(name),
                "dtype": str(series.dtype),
                "missing_rate": missing_rate,
                "n_unique": int(series.nunique(dropna=True)),
                "min": min_v,
                "max": max_v,
                "mean": mean_v,
                "top_values": top_values,
            }
        )

    fmt = dataset.format
    fmt_str = fmt.value if fmt is not None else "other"

    return {
        "dataset_id": dataset_id,
        "row_count": int(df.shape[0]),
        "format": fmt_str,
        "columns": profiles,
        "warnings": warnings,
    }


def _finite_or_none(value: Any) -> float | None:
    """Return the value if finite, else None (guards inf/nan -> JSON-safe)."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(f) or np.isinf(f):
        return None
    return f


def _jsonable(value: Any) -> Any:
    """Coerce numpy scalars to plain python so the dict serialises to JSON."""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value
