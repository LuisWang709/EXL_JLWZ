"""A production drift investigation scores the new batch, reaches H2 and keeps its healthy baseline."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from mrf.agents.rebuild.runner import ModelRunnerImpl
from mrf.contracts.models import ModelRecord, Pipeline, Report, Review, Run
from mrf.core import MRFError, PipelineState
from mrf.jobs import get_executor
from mrf.monitoring.registrar import TAG_BASELINE_DATASET, TAG_BASELINE_RUN, MonitoringRegistrarImpl
from mrf.orchestrator.graph import Orchestrator
from mrf.orchestrator.registry import Registry
from mrf.orchestrator.service import set_orchestrator, trigger_revalidation
from mrf.reporting.builder import ReportBuilderImpl
from mrf.storage import Collections, get_repo
from tests.unit.test_rebuild_agent import FIXTURES, LEGACY, _dataset, _rebuilt


async def test_trigger_batch_is_scored_and_signed_off_without_rebasing(tmp_path: Path) -> None:
    repo = get_repo()
    ctx = await _rebuilt("M001", LEGACY / "M001_sas_pd_scorecard" / "m001_pd_scorecard.sas")
    healthy = pd.read_csv(FIXTURES / "m001" / "input_sample.csv").astype({"credit_amount": float})
    await _dataset(tmp_path, "healthy", healthy, role="out_of_time")
    ctx.dataset_ids = ["healthy"]
    baseline = await ModelRunnerImpl().run(ctx, "healthy")
    await repo.put(Collections.RUNS, baseline.run_id, baseline)
    shifted = healthy.copy()
    shifted["credit_amount"] *= 4
    shifted["log_amount"] += 1.38629436112
    shifted["duration_months"] += 48
    await _dataset(tmp_path, "drifted", shifted, role="monitoring_batch", model_id=ctx.model.model_id)
    model = ctx.model.model_copy(update={
        "pipeline_id": ctx.pipeline_id, "lifecycle": "production",
        "tags": {TAG_BASELINE_DATASET: "healthy", TAG_BASELINE_RUN: baseline.run_id},
    })
    await repo.put(Collections.MODELS, model.model_id, model)
    pipeline = Pipeline(pipeline_id=ctx.pipeline_id, model_id=model.model_id,
                        dataset_ids=["healthy"], state=PipelineState.MONITORING)
    await repo.put(Collections.PIPELINES, pipeline.pipeline_id, pipeline)
    # Fresh checkpointer: recovery must carry the triggering batch in the durable job payload.
    orch = Orchestrator(registry=Registry.stubs(
        runner=ModelRunnerImpl(), report_builder=ReportBuilderImpl(), monitoring=MonitoringRegistrarImpl(),
    ))
    set_orchestrator(orch)
    job = await trigger_revalidation(model.model_id, "red drift", dataset_id="drifted")
    assert job.payload["artifacts"]["revalidation_dataset_ids"] == ["drifted"]
    with pytest.raises(MRFError, match="already queued"):
        await trigger_revalidation(model.model_id, "another batch", dataset_id="drifted")
    done = await get_executor().run_now(job.job_id)
    assert done.status == "succeeded", done.error
    assert done.result and done.result["gate"] == "H2"
    review = await repo.get(Collections.REVIEWS, done.result["review_id"], Review)
    assert review.payload["revalidation_dataset_ids"] == ["drifted"]
    run = await repo.get(Collections.RUNS, review.payload["run_ids"][0], Run)
    assert run.dataset_id == "drifted" and run.metrics["n_records"] == len(shifted)
    assert run.metrics["psi_reference"] == f"run:{baseline.run_id}" and run.metrics["psi_score"] > 0
    report = await repo.get(Collections.REPORTS, review.payload["validation_report_id"], Report)
    assert report.summary["revalidation_dataset_ids"] == ["drifted"]
    review.status = "approved"
    await repo.put(Collections.REVIEWS, review.review_id, review)
    outcome = await orch.resume(pipeline.pipeline_id, {"decision": "approve", "operator": "independent-reviewer"})
    assert outcome.state == PipelineState.MONITORING
    stored = await repo.get(Collections.MODELS, model.model_id, ModelRecord)
    assert stored.tags == model.tags
    assert (await repo.get(Collections.PIPELINES, pipeline.pipeline_id, Pipeline)).dataset_ids == ["healthy"]
    legacy = await trigger_revalidation(model.model_id, "operator requested validation on original datasets")
    assert legacy.payload["artifacts"] == {
        "revalidation_dataset_ids": [], "reference_dataset_id": None, "baseline_run_id": None,
    }
