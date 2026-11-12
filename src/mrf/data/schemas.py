"""pandera schemas for cleaned datasets. Owner: A2.

Registered schemas in ``SCHEMAS`` are the data-quality standard used by A4's
``DataQualityChecker``. A dataset links to one of these via ``Dataset.schema_name``.

Only German Credit is currently defined (the M001 model). Add one entry per
cleaned dataset as they are finalised.
"""

from __future__ import annotations

from typing import Any

import pandera as pa
from pandera.typing import DataFrame, Series

# ---------------------------------------------------------------- German Credit
# Cleaned German Credit (UCI Statlog) after recode + feature engineering.
# See scripts/preprocess_german_credit.py for the transformation pipeline.


class GermanCreditClean(pa.DataFrameModel):
    """Cleaned German Credit: target recoded + M001 features added."""

    id: Series[int] = pa.Field(ge=1)
    checking_status: Series[str] = pa.Field(isin=["A11", "A12", "A13", "A14"])
    credit_history: Series[str] = pa.Field(isin=["A30", "A31", "A32", "A33", "A34"])
    duration_months: Series[int] = pa.Field(ge=0)
    credit_amount: Series[float] = pa.Field(ge=0, le=15000.0)
    log_amount: Series[float] = pa.Field(nullable=True)
    age_band: Series[int] = pa.Field(isin=[1, 2, 3])
    default_flag: Series[int] = pa.Field(isin=[0, 1])

    class Config:
        strict = False
        coerce = False


SCHEMAS: dict[str, type[pa.DataFrameModel]] = {
    "german_credit_clean": GermanCreditClean,
}


def get_schema(name: str) -> type[pa.DataFrameModel]:
    """Return a registered schema by name; raise KeyError if unknown."""
    if name not in SCHEMAS:
        raise KeyError(f"unknown schema '{name}'; registered: {sorted(SCHEMAS)}")
    return SCHEMAS[name]


def validate(name: str, df: Any, **kwargs: Any) -> DataFrame:
    """Validate a DataFrame against a registered schema (A4 reuses this)."""
    schema = get_schema(name)
    return schema.validate(df, **kwargs)
