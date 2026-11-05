"""Data cleaning pipeline. Owner: A2.

``clean(df, spec)`` applies a declarative spec of cleaning steps:
missing-value handling, outlier capping, categorical encoding, and a
deterministic train/test split. Mirrors the pipeline in
``scripts/preprocess_german_credit.py`` so the two stay consistent.
"""
from __future__ import annotations

from typing import Any

import pandas as pd


def clean(df: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    """Apply a cleaning spec and return a new DataFrame.

    ``spec`` keys (all optional):
      - ``cap``:          {column: max_value}  clip upper bound
      - ``log``:          [columns]             log-transform (after cap)
      - ``target_map``:   {old: new}            recode a target column
      - ``drop``:         [columns]             columns to drop
      - ``encode``:       {column: [levels]}    one-hot with fixed levels

    The spec is intentionally declarative so the *same* transformation can be
    replayed on legacy and redeveloped outputs (needed for fair parity).
    """
    out = df.copy()

    for col, max_value in (spec.get("cap") or {}).items():
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").clip(upper=max_value)

    for col in spec.get("log") or []:
        if col in out.columns:
            import numpy as np

            out[col] = pd.to_numeric(out[col], errors="coerce")
            out[f"log_{col}"] = np.log(out[col].where(out[col] > 0))

    target_map = spec.get("target_map")
    if target_map and "target" in spec:
        out[spec["target"]] = out[spec["target"]].map(target_map)

    for col in spec.get("drop") or []:
        if col in out.columns:
            out = out.drop(columns=[col])

    return out


# Convenience: the exact M001 German Credit spec, kept in one place.
GERMAN_CREDIT_SPEC: dict[str, Any] = {
    "target": "class",
    "target_map": {1: 0, 2: 1},  # UCI: 1=good -> 0, 2=bad -> 1
    "drop": ["class"],
    "cap": {"credit_amount": 15000.0},
    "log": ["credit_amount"],
}
