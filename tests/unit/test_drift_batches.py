"""scripts/make_drift_batches.py builds the intended drift on synthetic German-Credit-shaped data (A4)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "make_drift_batches.py"


@pytest.fixture(scope="module")
def mdb() -> ModuleType:
    spec = importlib.util.spec_from_file_location("make_drift_batches", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def source() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    n = 300
    amount = rng.uniform(250, 14000, n).round(0)
    return pd.DataFrame(
        {
            "id": np.arange(1, n + 1),
            "checking_status": rng.choice(["A11", "A12", "A13", "A14"], n, p=[0.27, 0.27, 0.06, 0.40]),
            "credit_history": rng.choice(["A30", "A31", "A32", "A33", "A34"], n),
            "duration_months": rng.integers(4, 60, n),
            "credit_amount": amount,
            "log_amount": np.log(amount),
            "age_band": rng.choice([1, 2, 3], n, p=[0.15, 0.55, 0.30]),
            "default_flag": rng.choice([0, 1], n, p=[0.7, 0.3]),
        }
    )


def test_batches_have_the_intended_shape(mdb: ModuleType, source: pd.DataFrame) -> None:
    batches = mdb.build(source, rows=400, seed=42)
    assert [b[0] for b in batches.values()] == ["green", "amber", "red", "rejected"]
    assert all(len(b[2]) == 400 for b in batches.values())

    young = (batches["month_02_young_applicants"][2]["age_band"] == 1).mean()
    assert young == pytest.approx(2 * (source["age_band"] == 1).mean(), abs=0.01)

    downturn = batches["month_03_downturn"][2]
    assert (downturn["checking_status"] == "A11").mean() == pytest.approx(0.60, abs=0.01)
    assert downturn["credit_amount"].max() <= mdb.AMOUNT_CAP


def test_only_the_upstream_change_breaks_the_schema(mdb: ModuleType, source: pd.DataFrame) -> None:
    batches = mdb.build(source, rows=400, seed=42)
    verdict = {name: mdb.schema_ok(df) for name, (_, _, df) in batches.items()}
    assert verdict == {
        "month_01_normal": True,
        "month_02_young_applicants": True,
        "month_03_downturn": True,
        "month_04_upstream_change": False,
    }


def test_same_seed_same_batches(mdb: ModuleType, source: pd.DataFrame) -> None:
    a = mdb.build(source, rows=100, seed=1)["month_03_downturn"][2]
    b = mdb.build(source, rows=100, seed=1)["month_03_downturn"][2]
    pd.testing.assert_frame_equal(a, b)
