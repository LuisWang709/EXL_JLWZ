#!/usr/bin/env python3
"""Build the M001 "legacy" logistic-regression PD scorecard and export fixtures.

Owner: A2 (data engineering / rebuild engineer).

The M001 model is the synthetic "legacy" model the redevelopment agent must
reproduce in Python. This script fits it on the clean German Credit data and
writes the parity fixtures used by ``run_parity``:

    tests/fixtures/m001/
      input_sample.csv       (test set: 300 rows, used as model input)
      legacy_scores.csv      (id, pd_legacy, default_flag -- the ground truth)
      coefficients.json      (term -> estimate, reference coding)
      manifest.json          (model_id, source_language, columns, tolerance)

The same train/test split (seed 42) must be used by any redeveloped model so
the parity comparison is apples-to-apples.

Run:  uv run python scripts/build_m001_legacy.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

REPO_ROOT = Path(__file__).resolve().parents[1]
CLEAN = REPO_ROOT / "data" / "clean"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "m001"

# Reference levels must match the M001 SAS definition (4.2 in the tech design):
#   checking_status ref = A14
#   credit_history  ref = A34
#   age_band        ref = 3
FEATURES = ["checking_status", "credit_history", "duration_months", "log_amount", "age_band"]
TARGET = "default_flag"

MODEL_META = {
    "model_id": "M001",
    "name": "Retail application PD scorecard",
    "source_language": "SAS",
    "algorithm": "Logistic regression (logit link, reference coding)",
    "target": "default_flag (1 = bad credit)",
    "record_id_column": "id",
    "score_column": "pd_legacy",
    "tolerance": 1e-4,
}


def load_clean() -> pd.DataFrame:
    path = CLEAN / "german_credit_clean.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run preprocess_german_credit.py first.")
    return pd.read_csv(path)


def _design_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Build a reference-coded design matrix with explicit reference levels.

    The M001 SAS model uses reference coding with these reference levels:
      checking_status ref = A14
      credit_history  ref = A34
      age_band        ref = 3

    pandas ``get_dummies`` with ``drop_first=True`` drops the alphabetically /
    numerically first category, which is NOT the SAS reference. We therefore
    one-hot every level and then explicitly drop the reference column so the
    remaining columns match SAS reference coding exactly.
    """
    df = df.copy()
    cats_map = [
        ("checking_status", "A14", ["A11", "A12", "A13", "A14"]),
        ("credit_history", "A34", ["A30", "A31", "A32", "A33", "A34"]),
        ("age_band", 3, [1, 2, 3]),
    ]
    for col, ref, cats in cats_map:
        df[col] = pd.Categorical(df[col], categories=cats)

    dummies = pd.get_dummies(
        df[["checking_status", "credit_history", "age_band"]],
        columns=["checking_status", "credit_history", "age_band"],
        dtype=float,
    )
    # Drop the reference-level columns explicitly.
    drop_cols = [
        "checking_status_A14",
        "credit_history_A34",
        "age_band_3",
    ]
    dummies = dummies.drop(columns=[c for c in drop_cols if c in dummies.columns])

    numeric = df[["duration_months", "log_amount"]].astype(float)
    X = pd.concat([dummies, numeric], axis=1)
    return X


def main() -> int:
    df = load_clean()
    df = df.reset_index(drop=True)
    df["id"] = df.index + 1  # stable row id

    # Split identically to preprocess (seed 42, stratify).
    from sklearn.model_selection import train_test_split

    train, test = train_test_split(
        df, test_size=0.3, random_state=42, stratify=df["default_flag"]
    )
    train = train.reset_index(drop=True)
    test = test.reset_index(drop=True)

    X = _design_matrix(train)
    y = train[TARGET].astype(int)

    model = LogisticRegression(max_iter=1000, solver="lbfgs")
    model.fit(X, y)

    # Coefficients as term -> estimate, plus the intercept.
    coefficients = {"intercept": float(model.intercept_[0])}
    for name, coef in zip(X.columns, model.coef_[0]):
        coefficients[name] = float(coef)

    # Predict on the test set (same design matrix encoding).
    X_test = _design_matrix(test)
    # Align test columns to train columns.
    X_test = X_test.reindex(columns=X.columns, fill_value=0.0)
    pd_legacy = model.predict_proba(X_test)[:, 1]

    scores = pd.DataFrame(
        {
            "id": test["id"].values,
            "pd_legacy": np.round(pd_legacy, 8),
            "default_flag": test[TARGET].values,
        }
    )

    FIXTURES.mkdir(parents=True, exist_ok=True)

    # input_sample = the test set the model scored on (features + target).
    input_cols = ["id", "checking_status", "credit_history", "duration_months",
                  "credit_amount", "log_amount", "age_band", "default_flag"]
    test[input_cols].to_csv(FIXTURES / "input_sample.csv", index=False)

    scores.to_csv(FIXTURES / "legacy_scores.csv", index=False)

    with open(FIXTURES / "coefficients.json", "w") as f:
        json.dump(coefficients, f, indent=2)

    manifest = {**MODEL_META, "feature_columns": X.columns.tolist()}
    with open(FIXTURES / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print("M001 legacy model fit complete.")
    print(f"  features: {X.shape[1]}")
    print(f"  train: {len(train)} rows, test: {len(test)} rows")
    print(f"  coefficients: {len(coefficients)} terms")
    print(f"  wrote fixtures to {FIXTURES}/")
    print("\nCoefficients (top terms):")
    for k, v in list(coefficients.items())[:12]:
        print(f"    {k:32s} {v:+.6f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
