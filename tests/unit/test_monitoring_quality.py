"""QualityCheckerImpl (A4) on files, using A2's german_credit_clean schema where relevant."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mrf.contracts.models import ColumnInfo, QualityReport
from mrf.core import MRFCode, MRFError
from mrf.monitoring.quality import QualityCheckerImpl
from mrf.storage import Collections, get_repo
from tests.unit.monitoring_helpers import add_dataset, frame


def german(n: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    amount = rng.uniform(300, 14000, n).round(0)
    return pd.DataFrame(
        {
            "id": np.arange(1, n + 1),
            "checking_status": rng.choice(["A11", "A12", "A13", "A14"], n),
            "credit_history": rng.choice(["A30", "A31", "A32", "A33", "A34"], n),
            "duration_months": rng.integers(4, 60, n),
            "credit_amount": amount,
            "log_amount": np.log(amount),
            "age_band": rng.choice([1, 2, 3], n),
            "default_flag": rng.choice([0, 1], n),
        }
    )


def by_name(report: QualityReport) -> dict[str, str]:
    return {c.name: c.severity for c in report.checks}


async def test_clean_german_credit_passes_and_is_stored(tmp_path: Path) -> None:
    await add_dataset(tmp_path, "ds_ok", german(), schema_name="german_credit_clean")
    report = await QualityCheckerImpl().check("ds_ok")
    assert report.passed and by_name(report)["schema"] == "info"
    assert await get_repo().get(Collections.QUALITY, "ds_ok", QualityReport) == report


async def test_unknown_code_and_amount_cap_fail_the_schema(tmp_path: Path) -> None:
    df = german()
    df.loc[0, "checking_status"] = "A15"
    df.loc[1, "credit_amount"] = 20000.0
    await add_dataset(tmp_path, "ds_bad", df, schema_name="german_credit_clean")
    report = await QualityCheckerImpl().check("ds_bad")
    schema = next(c for c in report.checks if c.name == "schema")
    assert not report.passed and schema.severity == "red"
    assert schema.detail["n_failures"] >= 2 and schema.detail["examples"]


async def test_missing_rate_and_row_count_thresholds(tmp_path: Path) -> None:
    await add_dataset(tmp_path, "ds_amber", frame(n=100, missing=0.10))
    amber = await QualityCheckerImpl().check("ds_amber")
    assert amber.passed and by_name(amber)["missing_rate"] == "amber"

    await add_dataset(tmp_path, "ds_red", frame(n=100, missing=0.30))
    assert not (await QualityCheckerImpl().check("ds_red")).passed

    await add_dataset(tmp_path, "ds_small", frame(n=10))
    small = await QualityCheckerImpl().check("ds_small")
    assert small.passed and by_name(small)["row_count"] == "amber"


async def test_declared_columns_must_be_present(tmp_path: Path) -> None:
    cols = [ColumnInfo(name="x1", dtype="float"), ColumnInfo(name="income", dtype="float")]
    await add_dataset(tmp_path, "ds_cols", frame(), columns=cols)
    report = await QualityCheckerImpl().check("ds_cols")
    present = next(c for c in report.checks if c.name == "columns_present")
    assert not report.passed and present.detail["missing"] == ["income"]


async def test_unreadable_file_is_red_not_a_crash(tmp_path: Path) -> None:
    from mrf.contracts.models import Dataset

    await get_repo().put(
        Collections.DATASETS, "ds_gone", Dataset(dataset_id="ds_gone", name="gone", uri=str(tmp_path / "nope.csv"))
    )
    report = await QualityCheckerImpl().check("ds_gone")
    assert not report.passed and report.checks[0].name == "readable"


async def test_unknown_dataset_is_1404() -> None:
    with pytest.raises(MRFError) as err:
        await QualityCheckerImpl().check("ds_missing")
    assert err.value.code == MRFCode.NOT_FOUND
