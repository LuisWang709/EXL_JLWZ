#!/usr/bin/env python3
"""Parity check: compare a redeveloped Python model against the M001 legacy fixture.

Owner: A2 (data engineering / rebuild engineer).

This is the deterministic counterpart of the MCP tool ``run_parity``. Given the
legacy fixtures produced by ``build_m001_legacy.py``, it:

    1. loads the legacy scores + coefficients (the ground truth),
    2. "redevelops" the model in Python (a fresh logistic regression on the SAME
       train split -- this simulates what the rebuild agent produces),
    3. compares record-for-record predictions, coefficients, and Gini,
    4. reports PASS/FAIL against the tolerance in manifest.json.

The point of this script is to PROVE the fixture is a usable parity baseline:
the same model reproduced in Python must match within tolerance.

Run:  uv run python scripts/check_m001_parity.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

REPO_ROOT = Path(__file__).resolve().parents[1]
CLEAN = REPO_ROOT / "data" / "clean"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "m001"


def gini(y_true: np.ndarray, y_score: np.ndarray) -> float:
    """Gini coefficient = 2 * AUC - 1."""
    return 2.0 * roc_auc_score(y_true, y_score) - 1.0


def _design_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """Same reference-coded design matrix as build_m001_legacy.py."""
    df = df.copy()
    for col, cats in [
        ("checking_status", ["A11", "A12", "A13", "A14"]),
        ("credit_history", ["A30", "A31", "A32", "A33", "A34"]),
        ("age_band", [1, 2, 3]),
    ]:
        df[col] = pd.Categorical(df[col], categories=cats)
    dummies = pd.get_dummies(
        df[["checking_status", "credit_history", "age_band"]],
        columns=["checking_status", "credit_history", "age_band"],
        dtype=float,
    )
    drop_cols = ["checking_status_A14", "credit_history_A34", "age_band_3"]
    dummies = dummies.drop(columns=[c for c in drop_cols if c in dummies.columns])
    numeric = df[["duration_months", "log_amount"]].astype(float)
    return pd.concat([dummies, numeric], axis=1)


def main() -> int:
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    tolerance = float(manifest["tolerance"])
    legacy_coef = json.loads((FIXTURES / "coefficients.json").read_text())
    legacy_scores = pd.read_csv(FIXTURES / "legacy_scores.csv")

    # Rebuild the model in Python on the SAME train split (simulates the agent).
    clean = pd.read_csv(CLEAN / "german_credit_clean.csv").reset_index(drop=True)
    from sklearn.model_selection import train_test_split

    train, _ = train_test_split(
        clean, test_size=0.3, random_state=42, stratify=clean["default_flag"]
    )
    X = _design_matrix(train)
    y = train["default_flag"].astype(int)

    model = LogisticRegression(max_iter=1000, solver="lbfgs")
    model.fit(X, y)

    # Score the same test set as the fixture.
    test = pd.read_csv(CLEAN / "german_credit_test.csv").reset_index(drop=True)
    X_test = _design_matrix(test).reindex(columns=X.columns, fill_value=0.0)
    pd_python = model.predict_proba(X_test)[:, 1]

    # --- Parity checks ---
    results: dict[str, dict] = {}

    # 1. record count
    n_legacy = len(legacy_scores)
    n_python = len(pd_python)
    results["record_count"] = {
        "legacy": n_legacy,
        "python": n_python,
        "passed": n_legacy == n_python,
    }

    # 2. record-for-record PD difference
    # Align by id (legacy_scores has id, test set order matches fixture order).
    legacy_pd = legacy_scores["pd_legacy"].values
    diff = np.abs(legacy_pd - pd_python)
    max_diff = float(diff.max())
    results["pd_diff"] = {
        "max_abs_diff": max_diff,
        "tolerance": tolerance,
        "n_mismatches": int((diff > tolerance).sum()),
        "passed": max_diff <= tolerance,
    }

    # 3. coefficient comparison
    python_coef = {"intercept": float(model.intercept_[0])}
    for name, coef in zip(X.columns, model.coef_[0], strict=False):
        python_coef[name] = float(coef)
    coef_diffs = {
        k: abs(legacy_coef.get(k, 0.0) - python_coef.get(k, 0.0))
        for k in set(legacy_coef) | set(python_coef)
    }
    max_coef_diff = max(coef_diffs.values())
    results["coefficients"] = {
        "max_abs_diff": max_coef_diff,
        "tolerance": tolerance,
        "passed": max_coef_diff <= tolerance,
    }

    # 4. Gini comparison
    gini_legacy = gini(legacy_scores["default_flag"].values, legacy_pd)
    gini_python = gini(test["default_flag"].values, pd_python)
    results["gini"] = {
        "legacy": gini_legacy,
        "python": gini_python,
        "delta": abs(gini_legacy - gini_python),
        "passed": abs(gini_legacy - gini_python) <= 0.05,
    }

    # --- Report ---
    print("=" * 60)
    print("M001 PARITY CHECK")
    print("=" * 60)
    all_passed = True
    for name, r in results.items():
        status = "PASS" if r["passed"] else "FAIL"
        all_passed = all_passed and r["passed"]
        print(f"\n[{status}] {name}")
        for k, v in r.items():
            if k != "passed":
                print(f"    {k}: {v}")

    print("\n" + "=" * 60)
    print(f"OVERALL: {'PASS ✓' if all_passed else 'FAIL ✗'}")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
