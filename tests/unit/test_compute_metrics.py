"""MCP tool compute_metrics on registered datasets (M001 fixture)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pandas as pd
import pytest

from mrf.contracts.models import Dataset
from mrf.core import MRFCode, MRFError
from mrf.mcp_server.client import get_tools
from mrf.mcp_server.tools.metrics import compute_metrics
from mrf.storage import Collections, get_repo

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "m001"


def _register(tmp_path: Path, name: str, df: pd.DataFrame) -> str:
    path = tmp_path / f"{name}.csv"
    df.to_csv(path, index=False)
    ds = Dataset(dataset_id=f"ds_{name}", name=name, uri=str(path))
    asyncio.run(get_repo().put(Collections.DATASETS, ds.dataset_id, ds))
    return ds.dataset_id


@pytest.fixture
def m001(tmp_path: Path) -> pd.DataFrame:
    data = pd.read_csv(FIXTURES / "input_sample.csv")
    scores = pd.read_csv(FIXTURES / "legacy_scores.csv")[["id", "pd_legacy"]]
    return data.merge(scores, on="id")


def test_all_applicable_metrics_for_m001(tmp_path: Path, m001: pd.DataFrame) -> None:
    ds = _register(tmp_path, "m001", m001)
    ref = _register(tmp_path, "m001_ref", m001)
    out = asyncio.run(
        compute_metrics(ds, "pd_legacy", "default_flag", reference_dataset_id=ref, segment_column="age_band")
    )
    m = out["metrics"]
    assert out["n_records"] == len(m001) and out["warnings"] == []
    assert set(m) == {"auc", "gini", "ks", "brier", "hosmer_lemeshow", "psi", "csi", "fairness"}
    assert 0.5 < m["auc"] < 1 and m["gini"] == pytest.approx(2 * m["auc"] - 1)
    assert m["psi"] == pytest.approx(0.0) and set(m["csi"]) >= {"duration_months", "age_band"}
    assert "id" not in m["csi"] and "default_flag" not in m["csi"]
    assert set(m["fairness"]["segments"]) == {"1", "2", "3"}


def test_explicit_metric_that_cannot_run_is_a_warning(tmp_path: Path, m001: pd.DataFrame) -> None:
    ds = _register(tmp_path, "m001", m001)
    out = asyncio.run(compute_metrics(ds, "duration_months", "default_flag", metrics=["auc", "brier", "psi"]))
    assert set(out["metrics"]) == {"auc"}
    assert any("brier skipped" in w for w in out["warnings"]) and any("psi skipped" in w for w in out["warnings"])


def test_errors(tmp_path: Path, m001: pd.DataFrame) -> None:
    ds = _register(tmp_path, "m001", m001)
    with pytest.raises(MRFError) as err:
        asyncio.run(compute_metrics(ds, "nope", "default_flag"))
    assert err.value.code == MRFCode.INPUT_DATA_SCHEMA and err.value.field == "score_column"
    with pytest.raises(MRFError) as err:
        asyncio.run(compute_metrics(ds, "pd_legacy", metrics=["accuracy"]))
    assert err.value.code == MRFCode.INPUT_BODY
    with pytest.raises(MRFError) as err:
        asyncio.run(compute_metrics("ds_missing", "pd_legacy"))
    assert err.value.code == MRFCode.NOT_FOUND


def test_reverse_oriented_score_warns(tmp_path: Path, m001: pd.DataFrame) -> None:
    m001["points"] = 600 - 100 * m001["pd_legacy"]
    ds = _register(tmp_path, "m001", m001)
    out = asyncio.run(compute_metrics(ds, "points", "default_flag", metrics=["auc"]))
    assert out["metrics"]["auc"] < 0.5 and "reverse-oriented" in out["warnings"][0]


def test_callable_through_the_gateway(tmp_path: Path, m001: pd.DataFrame) -> None:
    ds = _register(tmp_path, "m001", m001)
    tools = get_tools()
    out = asyncio.run(
        tools.call("compute_metrics", dataset_id=ds, score_column="pd_legacy", target_column="default_flag")
    )
    assert "auc" in out["metrics"] and tools.records[0].ok
