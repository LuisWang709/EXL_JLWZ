#!/usr/bin/env python3
"""Build the parity fixtures of the second and third rebuild targets (M002, M004).

The "legacy" systems (R for M002, SAS for M004) are simulated: the model in ``models/legacy/<id>/`` is fitted
here with an unpenalised maximum-likelihood / least-squares fit, which is what R ``glm`` and SAS ``PROC REG``
compute, and the exports a legacy system would hand over are written:

    tests/fixtures/<id>/input_sample.csv    records the legacy system scored
    tests/fixtures/<id>/legacy_scores.csv   record id + legacy score
    tests/fixtures/<id>/coefficients.json   parameter estimates
    tests/fixtures/<id>/manifest.json       id / score column, link, tolerance

    data/clean/taiwan_default_{train,test}.csv   M002 development / hold-out data (git-ignored)
    data/clean/loan_book_{train,test}.csv        M004 synthetic loan book (git-ignored)

M002 uses the UCI "Default of Credit Card Clients" data (``scripts/get_data.py``; reading the .xls needs xlrd:
``uv run --with xlrd python scripts/build_legacy_fixtures.py``). M004 is a synthetic loan book derived from the
cleaned German Credit data with a fixed seed - it is NOT real pricing data.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.model_selection import train_test_split

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW = REPO_ROOT / "data" / "raw"
CLEAN = REPO_ROOT / "data" / "clean"
FIXTURES = REPO_ROOT / "tests" / "fixtures"
SEED = 42


def _write(fixture: str, sample: pd.DataFrame, scores: pd.DataFrame, coef: dict[str, float], manifest: dict) -> None:
    out = FIXTURES / fixture
    out.mkdir(parents=True, exist_ok=True)
    sample.to_csv(out / "input_sample.csv", index=False, lineterminator="\n")
    scores.to_csv(out / "legacy_scores.csv", index=False, lineterminator="\n")
    (out / "coefficients.json").write_bytes((json.dumps(coef, indent=2) + "\n").encode())
    (out / "manifest.json").write_bytes((json.dumps(manifest, indent=2) + "\n").encode())
    print(f"{fixture}: {len(sample)} records, {len(coef)} estimates -> {out}")


# ------------------------------------------------------------------ M002: R glm(binomial), Taiwan card default
def build_m002() -> None:
    raw = pd.read_excel(RAW / "taiwan_credit_default.xls", header=1)
    df = pd.DataFrame(
        {
            "id": raw["ID"].astype(int),
            "limit_bal": raw["LIMIT_BAL"].astype(float),
            "bill_amt1": raw["BILL_AMT1"].astype(float),
            "pay_0": raw["PAY_0"].astype(int),
            "pay_2": raw["PAY_2"].astype(int),
            "age": raw["AGE"].astype(int),
            # 1 graduate school, 2 university, 3 high school, 4 other (0 / 5 / 6 are undocumented -> other)
            "education": raw["EDUCATION"].where(raw["EDUCATION"].isin([1, 2, 3]), 4).astype(int),
            "default_next_month": raw["default payment next month"].astype(int),
        }
    )
    df["util"] = df["bill_amt1"] / np.maximum(df["limit_bal"], 1.0)
    train, test = train_test_split(df, test_size=0.3, random_state=SEED, stratify=df["default_next_month"])
    CLEAN.mkdir(parents=True, exist_ok=True)
    train.to_csv(CLEAN / "taiwan_default_train.csv", index=False)
    test.to_csv(CLEAN / "taiwan_default_test.csv", index=False)

    def design(frame: pd.DataFrame) -> pd.DataFrame:
        x = frame[["limit_bal", "util", "pay_0", "pay_2", "age"]].astype(float).copy()
        for level in (1, 3, 4):  # reference level: 2 (university), as relevel(factor(education), ref = "2")
            x[f"education_{level}"] = (frame["education"] == level).astype(float)
        return sm.add_constant(x, has_constant="add")

    fit = sm.GLM(train["default_next_month"], design(train), family=sm.families.Binomial()).fit()
    coef = {("intercept" if k == "const" else k): float(v) for k, v in fit.params.items()}

    sample = test.sort_values("id").head(500).reset_index(drop=True)
    scores = pd.DataFrame(
        {
            "id": sample["id"],
            "pd_legacy": np.asarray(fit.predict(design(sample)), dtype=float),
            "default_next_month": sample["default_next_month"],
        }
    )
    columns = ["id", "limit_bal", "bill_amt1", "util", "pay_0", "pay_2", "age", "education", "default_next_month"]
    _write(
        "m002",
        sample[columns],
        scores,
        coef,
        {
            "model_id": "M002",
            "name": "Credit card default model",
            "source_language": "R",
            "algorithm": "glm(family = binomial(link = 'logit')), treatment contrasts",
            "target": "default_next_month (1 = default)",
            "record_id_column": "id",
            "score_column": "pd_legacy",
            "link": "logit",
            "tolerance": 1e-6,
            "feature_columns": [k for k in coef if k != "intercept"],
        },
    )


# ------------------------------------------------------------------ M004: SAS PROC REG, synthetic loan pricing
def build_m004() -> None:
    base = pd.read_csv(CLEAN / "german_credit_clean.csv")
    rng = np.random.default_rng(SEED)
    grade = base["credit_history"].map({"A30": 5, "A31": 4, "A32": 3, "A33": 2, "A34": 1}).astype(int)
    book = pd.DataFrame(
        {
            "id": base["id"].astype(int),
            "term_months": base["duration_months"].astype(int),
            "loan_amount": base["credit_amount"].astype(float),
            "risk_grade_num": grade,
            "ltv": np.round(rng.beta(5, 3, len(base)), 4),
        }
    )
    book["term_years"] = book["term_months"] / 12
    book["price_margin"] = np.round(
        1.40
        + 0.11 * book["term_years"]
        - 0.000035 * book["loan_amount"]
        + 0.42 * book["risk_grade_num"]
        + 1.15 * book["ltv"]
        + rng.normal(0, 0.25, len(book)),
        4,
    )
    train, test = train_test_split(book, test_size=0.3, random_state=SEED)
    train.to_csv(CLEAN / "loan_book_train.csv", index=False)
    test.to_csv(CLEAN / "loan_book_test.csv", index=False)

    features = ["term_years", "loan_amount", "risk_grade_num", "ltv"]
    fit = sm.OLS(train["price_margin"], sm.add_constant(train[features], has_constant="add")).fit()
    coef = {("intercept" if k == "const" else k): float(v) for k, v in fit.params.items()}
    sample = test.sort_values("id").reset_index(drop=True)
    scores = pd.DataFrame(
        {
            "id": sample["id"],
            "margin_legacy": np.asarray(fit.predict(sm.add_constant(sample[features], has_constant="add"))),
            "price_margin": sample["price_margin"],
        }
    )
    _write(
        "m004",
        sample[["id", "term_months", "term_years", "loan_amount", "risk_grade_num", "ltv", "price_margin"]],
        scores,
        coef,
        {
            "model_id": "M004",
            "name": "Personal loan pricing margin model",
            "source_language": "SAS",
            "algorithm": "PROC REG (ordinary least squares)",
            "target": "price_margin (percentage points over funding cost)",
            "record_id_column": "id",
            "score_column": "margin_legacy",
            "link": "identity",
            "tolerance": 1e-6,
            "feature_columns": features,
            "synthetic": True,
        },
    )


if __name__ == "__main__":
    build_m002()
    build_m004()
