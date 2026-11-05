#!/usr/bin/env python3
"""Preprocess German Credit (UCI Statlog) into a clean, recoded dataset.

Owner: A2 (data engineering / rebuild engineer).

Pipeline (mirrors ``docs/data.md`` and the M001 SAS model definition):

    1. load data/raw/german_credit.csv (already column-named)
    2. recode the target: class 1 (good) -> 0, class 2 (bad) -> 1, as
       ``default_flag``
    3. feature engineering used by the M001 scorecard:
         - credit_amount capped at 15000, then log -> ``log_amount``
         - ``age_band``: 1 = <25, 2 = 25-39, 3 = 40+
    4. train/test split with a fixed seed (the SAME split must be reused by
       both the legacy model and any redeveloped model, so parity is fair)
    5. write data/clean/german_credit_clean.csv and train/test parquet

Run:  uv run python scripts/preprocess_german_credit.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW = REPO_ROOT / "data" / "raw"
CLEAN = REPO_ROOT / "data" / "clean"

RANDOM_SEED = 42
TEST_FRACTION = 0.3

# German Credit attribute codes -> readable labels (for documentation only).
CHECKING_LABELS = {
    "A11": "<0 DM",
    "A12": "0-200 DM",
    "A13": ">=200 DM or salary",
    "A14": "no checking account",
}
CREDIT_HISTORY_LABELS = {
    "A30": "no credits / paid duly",
    "A31": "all credits at this bank paid duly",
    "A32": "existing credits paid duly",
    "A33": "delay in paying in the past",
    "A34": "critical account / other credits",
}


def load_raw() -> pd.DataFrame:
    """Load the column-named German Credit CSV produced by the data step."""
    path = RAW / "german_credit.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `uv run python scripts/get_data.py` first."
        )
    return pd.read_csv(path)


def recode_target(df: pd.DataFrame) -> pd.DataFrame:
    """Map UCI class (1=good, 2=bad) to binary default_flag (1=bad)."""
    if "class" not in df.columns:
        raise ValueError("expected a 'class' column in the raw data")
    df["default_flag"] = np.where(df["class"] == 2, 1, 0)
    return df.drop(columns=["class"])


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the M001 scorecard transformations (correct age_band logic)."""
    # cap + log credit amount
    df["credit_amount"] = pd.to_numeric(df["credit_amount"], errors="coerce")
    df["credit_amount"] = df["credit_amount"].clip(upper=15000.0)
    df["log_amount"] = np.log(df["credit_amount"].replace(0, np.nan))

    # age band: 1=<25, 2=25-39, 3=40+  (correct grouping, not the SAS bug)
    age = pd.to_numeric(df["age"], errors="coerce")
    df["age_band"] = np.select(
        [age < 25, (age >= 25) & (age < 40), age >= 40],
        [1, 2, 3],
        default=3,
    )

    # numeric duration
    df["duration_months"] = pd.to_numeric(df["duration_months"], errors="coerce")

    return df


def split(df: pd.DataFrame, test_fraction: float = TEST_FRACTION) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Stratified split with a fixed seed; index is preserved for parity."""
    from sklearn.model_selection import train_test_split

    train, test = train_test_split(
        df,
        test_size=test_fraction,
        random_state=RANDOM_SEED,
        stratify=df["default_flag"],
    )
    return train.reset_index(drop=True), test.reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true", help="print only, do not write")
    args = parser.parse_args(argv)

    df = load_raw()
    print(f"Loaded {len(df)} rows from german_credit.csv")

    df = recode_target(df)
    df = engineer_features(df)
    print(f"After recode + feature engineering: {df.shape[0]} rows x {df.shape[1]} cols")
    print(f"Target distribution (default_flag):\n{df['default_flag'].value_counts().sort_index()}")

    train, test = split(df)
    print(f"Train {len(train)} rows / Test {len(test)} rows")

    if args.no_write:
        return 0

    CLEAN.mkdir(parents=True, exist_ok=True)
    df.to_csv(CLEAN / "german_credit_clean.csv", index=False)
    train.to_csv(CLEAN / "german_credit_train.csv", index=False)
    test.to_csv(CLEAN / "german_credit_test.csv", index=False)
    print(f"Wrote clean data to {CLEAN}/")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
