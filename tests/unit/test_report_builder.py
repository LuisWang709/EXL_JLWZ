"""ReportBuilderImpl: RAG statuses from stored pipeline objects, number ledger check, fairness by segment."""

from __future__ import annotations

import copy
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from mrf.agents.doc.agent import DocAgent
from mrf.config import get_policy
from mrf.contracts.agents import StepContext
from mrf.contracts.models import (
    ParityResult,
    Pipeline,
    Rebuild,
    Run,
    StateTransition,
    Usage,
    utcnow,
)
from mrf.core import MRFCode, MRFError, PipelineState
from mrf.rating.rater import DocRater
from mrf.reporting import builder
from mrf.reporting.builder import ReportBuilderImpl
from mrf.reporting.numbers import Ledger, check_numbers
from mrf.storage import Collections, get_blobs, get_repo
from tests.unit.a3_helpers import FIXTURES, m001_context, scored_m001_dataset

S = PipelineState


async def _pipeline_ctx(
    tmp_path: Path,
    metrics: dict[str, Any] | None = None,
    parity_ok: bool = True,
    with_outputs: bool = True,
) -> StepContext:
    """M001 with a stored document, rating, rebuild, usability run (+ scored output file) and pipeline."""
    repo = get_repo()
    ds = await scored_m001_dataset(tmp_path)
    ctx = await m001_context(dataset_ids=[ds.dataset_id])
    doc = await DocAgent().draft(ctx)
    rating = await DocRater().rate(ctx, doc)
    await repo.put(Collections.DOCUMENTS, doc.doc_id, doc)
    await repo.put(Collections.RATINGS, rating.rating_id, rating)
    rb = Rebuild(
        rebuild_id="rb_m001",
        model_id=ctx.model.model_id,
        attempt=2,
        status="passed" if parity_ok else "failed",
        parity=ParityResult(
            passed=parity_ok, n_records=300, n_mismatches=0 if parity_ok else 4, max_abs_diff=3e-9, tolerance=1e-6
        ),
    )
    await repo.put(Collections.REBUILDS, rb.rebuild_id, rb)
    outputs = []
    if with_outputs:
        scores = pd.read_csv(FIXTURES / "m001" / "legacy_scores.csv")[["id", "pd_legacy"]]
        scores = scores.rename(columns={"pd_legacy": "pd_python"})  # runner output convention (frames.SCORE_COLUMNS)
        ref = await get_blobs().put_bytes(
            "runs/run_m001/scores.csv", scores.to_csv(index=False).encode(), filename="scores.csv"
        )
        outputs = [ref]
    run = Run(
        run_id="run_m001",
        model_id=ctx.model.model_id,
        dataset_id=ds.dataset_id,
        status="succeeded",
        metrics=metrics
        if metrics is not None
        else {
            "auc": 0.7712,
            "gini": 0.5424,
            "ks": 0.4301,
            "brier": 0.1801,
            "psi_score": 0.031,
            "hosmer_lemeshow": {"statistic": 9.1, "p_value": 0.33},
        },
        outputs=outputs,
    )
    await repo.put(Collections.RUNS, run.run_id, run)
    start = utcnow() - timedelta(minutes=6)
    history = [
        StateTransition(from_state=None, to_state=S.RECEIVED, at=start),
        StateTransition(from_state=S.RECEIVED, to_state=S.CLASSIFIED, at=start + timedelta(minutes=1)),
        StateTransition(from_state=S.CLASSIFIED, to_state=S.DOC_DRAFTING, at=start + timedelta(minutes=2)),
        StateTransition(from_state=S.DOC_DRAFTING, to_state=S.AWAITING_DOC_APPROVAL, at=start + timedelta(minutes=3)),
        StateTransition(
            from_state=S.AWAITING_DOC_APPROVAL, to_state=S.REBUILDING, actor="albert", at=start + timedelta(minutes=4)
        ),
        StateTransition(from_state=S.REBUILDING, to_state=S.USABILITY_RUN, at=start + timedelta(minutes=5)),
    ]
    p = Pipeline(
        pipeline_id=ctx.pipeline_id,
        model_id=ctx.model.model_id,
        state=S.USABILITY_RUN,
        attempts={"doc": 1, "parity": 2},
        dataset_ids=[ds.dataset_id],
        history=history,
        usage=Usage(prompt_tokens=7000, completion_tokens=700, cost_eur=0.0014, llm_calls=3),
        created_at=start,
    )
    await repo.put(Collections.PIPELINES, p.pipeline_id, p)
    arts = {"doc_id": doc.doc_id, "rating_id": rating.rating_id, "rebuild_id": rb.rebuild_id, "run_ids": [run.run_id]}
    return ctx.model_copy(update={"artifacts": arts})


def m_di(summary: dict[str, Any]) -> float:
    return float(summary["metrics"]["fairness.disparate_impact"])


async def test_analysis_report_full_data(tmp_path: Path) -> None:
    ctx = await _pipeline_ctx(tmp_path)
    report = await ReportBuilderImpl().build(ctx, "analysis")
    s = report.summary
    assert report.type == "analysis" and report.artifact is not None
    # on the 300-row fixture the under-30 band is approved 0.69x as often as the 45+ band -> red
    assert s["statuses"] == {"consistency": "green", "performance": "green", "stability": "green", "fairness": "red"}
    assert report.rag_status == "red" and m_di(s) == pytest.approx(0.6922, abs=1e-4)
    check = s["number_check"]
    assert check["passed"] and check["mismatched"] == [] and check["untraceable"] == [] and check["numbers"] > 40
    m = s["metrics"]
    assert m["performance.gini"] == 0.5424 and m["parity.n_records"] == 300 and m["process.doc_attempts"] == 1
    assert set(k.split(".")[2] for k in m if k.startswith("fairness.segments.")) == {"1", "2", "3"}
    assert m["process.automation_rate"] == pytest.approx(5 / 6) and m["process.elapsed_minutes"] == pytest.approx(5)
    gini = next(n for n in s["numbers"] if n["key"] == "performance.gini")
    assert gini == {"key": "performance.gini", "text": "0.542", "source": "run:run_m001.metrics.gini"}
    assert "run:run_m001 outputs (pd_python) + dataset:ds_m001_scored (age_band)" in s["sources"]["fairness.n"]
    page = (await get_blobs().get_bytes(report.artifact.uri)).decode()
    assert '<span class="num" data-key="performance.gini" data-spec=".3f">0.542</span>' in page
    assert "Manual baseline not measured yet" in page and "Fairness is red" in page


async def test_validation_report_is_the_h2_pack(tmp_path: Path) -> None:
    ctx = await _pipeline_ctx(tmp_path)
    report = await ReportBuilderImpl().build(ctx, "validation")
    page = (await get_blobs().get_bytes(report.artifact.uri)).decode()  # type: ignore[union-attr]
    assert "Validation report - H2 sign-off pack" in page and "Sign-off checklist (H2)" in page
    assert report.summary["recommendation"].startswith("Do not approve")
    assert report.summary["number_check"]["passed"]
    assert report.summary["metrics"]["documentation.rating_total"] >= 80


@pytest.mark.parametrize(
    ("metrics", "parity_ok", "expected", "recommendation"),
    [
        ({"gini": 0.35, "psi_score": 0.05}, True, {"performance": "amber", "stability": "green"}, "Approve only with"),
        ({"gini": 0.25, "psi_score": 0.30}, True, {"performance": "red", "stability": "red"}, "Do not approve"),
        ({"gini": 0.55, "psi_score": 0.12}, False, {"consistency": "red", "stability": "amber"}, "Do not approve"),
    ],
)
async def test_thresholds(
    tmp_path: Path, metrics: dict[str, float], parity_ok: bool, expected: dict[str, str], recommendation: str
) -> None:
    ctx = await _pipeline_ctx(tmp_path, metrics=metrics, parity_ok=parity_ok, with_outputs=False)
    report = await ReportBuilderImpl().build(ctx, "analysis")
    for dim, status in expected.items():
        assert report.summary["statuses"][dim] == status
    assert report.summary["statuses"]["fairness"] is None
    assert report.summary["recommendation"].startswith(recommendation)
    assert any("Fairness not assessed" in w for w in report.summary["warnings"])


async def test_stub_metrics_and_missing_inputs_are_reported(tmp_path: Path) -> None:
    ctx = await m001_context()
    report = await ReportBuilderImpl().build(ctx, "analysis")
    assert report.rag_status is None and set(report.summary["statuses"].values()) == {None}
    assert report.summary["number_check"]["passed"]
    warnings = " ".join(report.summary["warnings"])
    assert "No rebuild" in warnings and "No Gini" in warnings
    ctx2 = await _pipeline_ctx(tmp_path, metrics={"stub": True, "gini": 0.52, "ks": 0.38, "psi_score": 0.03})
    stub = await ReportBuilderImpl().build(ctx2, "analysis")
    assert any("stub runner" in w for w in stub.summary["warnings"])


async def test_measured_baseline_adds_savings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = copy.deepcopy(get_policy())
    policy["reporting"].update(manual_baseline_hours=16.0, analyst_cost_eur_per_hour=60.0)
    monkeypatch.setattr(builder, "get_policy", lambda: policy)
    ctx = await _pipeline_ctx(tmp_path, with_outputs=False)
    m = (await ReportBuilderImpl().build(ctx, "analysis")).summary["metrics"]
    assert m["process.hours_saved"] == pytest.approx(16 - 5 / 60)
    assert m["process.cost_saved_eur"] == pytest.approx(16 * 60 - 0.0014)


def test_number_check_catches_mismatch_and_untraceable_numbers() -> None:
    ledger = Ledger({"g": 0.4})
    page = f"<html><head><title>v 2</title></head><body><p>Gini {ledger.num('g')} and 0.87</p>"
    page += (
        '<p><span class="num" data-key="g" data-spec=".3f">0.500</span> <span class="meta">mdl 2026-11-09</span></p>'
    )
    check = check_numbers(page, ledger.facts)
    assert check["numbers"] == 2 and check["untraceable"] == ["0.87"]
    assert check["mismatched"] == [{"key": "g", "shown": "0.500", "source_value": 0.4}] and not check["passed"]


async def test_report_with_a_stray_number_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = await m001_context()
    monkeypatch.setattr(builder, "render", lambda *a, **k: "<html><body>Gini 0.87</body></html>")
    with pytest.raises(MRFError) as err:
        await ReportBuilderImpl().build(ctx, "validation")
    assert err.value.code == MRFCode.INTERNAL and err.value.detail["untraceable"] == ["0.87"]


async def test_other_report_types() -> None:
    ctx = await m001_context()
    with pytest.raises(MRFError) as err:
        await ReportBuilderImpl().build(ctx, "monitoring")
    assert err.value.code == MRFCode.INTERNAL and "A4" in err.value.message
    with pytest.raises(MRFError) as err:
        await ReportBuilderImpl().build(ctx, "weekly")
    assert err.value.code == MRFCode.INPUT_BODY
