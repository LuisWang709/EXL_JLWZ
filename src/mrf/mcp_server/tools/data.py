"""Owner: A2."""

from __future__ import annotations

from typing import Any


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
    raise NotImplementedError
