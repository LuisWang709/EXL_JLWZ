"""One monitoring batch end to end, plus the job handlers. Owner: A4.

    quality check -> ModelRunner.run(kind="batch") -> PSI/CSI vs the baseline -> MonitoringMetric
    -> amber/red Alert -> on red: trigger_revalidation (pipeline goes back to usability_run)

Runs inside the API process as a job (``monitoring_batch`` / ``monitoring_tick``): business data and the job
queue live there, so a separate container could not see them. The Container Apps Job only calls
``POST /api/v1/monitoring/runs`` on a timer.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mrf.contracts.agents import ModelRunner, StepContext
from mrf.contracts.models import Alert, Dataset, Job, ModelRecord, MonitoringMetric, QualityCheck, Run, Schedule
from mrf.core import MRFCode, MRFError
from mrf.core.ids import new_id
from mrf.jobs import register_handler
from mrf.monitoring.drift import classify, compute_psi, pick_features
from mrf.monitoring.frames import load_frame, run_scores
from mrf.monitoring.quality import QualityCheckerImpl
from mrf.monitoring.registrar import TAG_BASELINE_DATASET, TAG_BASELINE_RUN
from mrf.storage import Collections, get_repo

log = logging.getLogger(__name__)


def metric_key(model_id: str, dataset_id: str) -> str:
    return f"{model_id}:{dataset_id}"


def _runner() -> ModelRunner:
    from mrf.orchestrator.registry import Registry

    return Registry.discover().runner


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _missing_by_column(checks: list[QualityCheck]) -> dict[str, float]:
    found = next((c.detail.get("by_column") for c in checks if c.name == "missing_rate"), None)
    return {str(k): float(v) for k, v in (found or {}).items()}


async def _alert(model_id: str, severity: str, kind: str, message: str, detail: dict[str, Any]) -> Alert:
    alert = Alert(
        alert_id=new_id("alert"),
        model_id=model_id,
        severity=severity,  # type: ignore[arg-type]
        kind=kind,  # type: ignore[arg-type]
        message=message[:500],
        detail=detail,
    )
    await get_repo().put(Collections.ALERTS, alert.alert_id, alert)
    log.warning(
        "monitoring alert", extra={"model_id": model_id, "severity": severity, "kind": kind, "alert_message": message}
    )
    return alert


async def _revalidate(model_id: str, reasons: list[str]) -> str | None:
    """Job id of the re-validation, or None if the pipeline is not in ``monitoring`` (already re-validating)."""
    from mrf.orchestrator.service import trigger_revalidation

    try:
        job = await trigger_revalidation(model_id, reason="; ".join(reasons) or "drift above threshold")
    except MRFError as exc:
        if exc.code != MRFCode.INVALID_STATE:
            raise
        log.info("monitoring: re-validation not triggered for %s: %s", model_id, exc.message)
        return None
    return job.job_id


async def process_batch(model_id: str, dataset_id: str) -> MonitoringMetric:
    repo = get_repo()
    model = await repo.get(Collections.MODELS, model_id, ModelRecord)
    key = metric_key(model_id, dataset_id)
    done = await repo.get_or_none(Collections.METRICS, key, MonitoringMetric)
    if done is not None:  # idempotent: one metric (and one set of alerts) per batch
        return done

    # 1. data quality - a rejected batch is a data problem, not a model problem: alert, no re-validation
    quality = await QualityCheckerImpl().check(dataset_id)
    if not quality.passed:
        failed = [c.name for c in quality.checks if c.severity == "red"]
        rejection: dict[str, Any] = {"batch_id": dataset_id, "failed_checks": failed}
        rows = next((c.value for c in quality.checks if c.name == "row_count"), None)
        rejected = MonitoringMetric(
            model_id=model_id,
            batch_id=dataset_id,
            row_count=int(rows) if isinstance(rows, int | float) else None,
            missing_rate=_missing_by_column(quality.checks),
            status="red",
        )
        await repo.put(Collections.METRICS, key, rejected)  # recorded once, so the next tick does not re-alert
        await _alert(model_id, "red", "data_quality", f"batch {dataset_id} rejected: {', '.join(failed)}", rejection)
        raise MRFError(MRFCode.DATA_QUALITY_FAILED, f"batch {dataset_id} failed: {', '.join(failed)}", detail=rejection)

    # 2. score the batch with the rebuilt model (A2)
    baseline_id = model.tags.get(TAG_BASELINE_DATASET)
    if not baseline_id:
        raise MRFError(MRFCode.INVALID_STATE, f"{model_id} has no monitoring baseline - is it registered?")
    baseline_run_id = model.tags.get(TAG_BASELINE_RUN)
    ctx = StepContext(
        pipeline_id=model.pipeline_id or "",
        model=model,
        dataset_ids=[dataset_id],
        artifacts={"reference_dataset_id": baseline_id, "baseline_run_id": baseline_run_id},
    )
    run = await _runner().run(ctx, dataset_id, "batch")
    await repo.put(Collections.RUNS, run.run_id, run)

    # 3. drift vs the baseline (PSI/CSI from A3's mrf.validation)
    ds = await repo.get(Collections.DATASETS, dataset_id, Dataset)
    baseline = await repo.get(Collections.DATASETS, baseline_id, Dataset)
    baseline_run = await repo.get_or_none(Collections.RUNS, baseline_run_id, Run) if baseline_run_id else None
    base_df, batch_df = await asyncio.gather(asyncio.to_thread(load_frame, baseline), asyncio.to_thread(load_frame, ds))
    features = pick_features(model, baseline, base_df, batch_df)
    base_scores, batch_scores = await asyncio.gather(
        asyncio.to_thread(run_scores, baseline_run), asyncio.to_thread(run_scores, run)
    )
    psi = await asyncio.to_thread(compute_psi, base_df, batch_df, features, base_scores, batch_scores)
    reported = _number(run.metrics.get("psi_score"))
    if "__score__" not in psi and reported is not None:  # the runner computed score PSI itself
        psi["__score__"] = reported

    gini = _number(run.metrics.get("gini"))
    baseline_gini = _number(baseline_run.metrics.get("gini")) if baseline_run else None
    status, reasons = classify(psi, gini, baseline_gini)

    # 4. persist, alert, re-validate
    metric = MonitoringMetric(
        model_id=model_id,
        batch_id=dataset_id,
        row_count=len(batch_df),
        missing_rate=_missing_by_column(quality.checks),
        psi={k: round(v, 6) for k, v in psi.items()},
        gini=gini,
        status=status,
    )
    await repo.put(Collections.METRICS, key, metric)
    if status != "green":
        detail: dict[str, Any] = {"batch_id": dataset_id, "run_id": run.run_id, "psi": metric.psi, "gini": gini}
        if status == "red":
            detail["revalidation_job_id"] = await _revalidate(model_id, reasons)
        await _alert(model_id, status, "drift", "; ".join(reasons), detail)
    log.info(
        "monitoring batch",
        extra={"model_id": model_id, "batch_id": dataset_id, "status": status, "max_psi": max(psi.values(), default=0)},
    )
    return metric


async def process_pending(model_id: str | None = None) -> dict[str, Any]:
    """Every not-yet-processed ``monitoring_batch`` dataset of every enabled schedule (or of one model)."""
    repo = get_repo()
    where: dict[str, Any] = {"enabled": True}
    if model_id:
        where["model_id"] = model_id
    schedules = await repo.find(Collections.SCHEDULES, Schedule, where=where, page_size=1000, order_by="model_id")
    summary: dict[str, Any] = {"models": [], "processed": [], "rejected": [], "failed": []}
    for sched in schedules.items:
        summary["models"].append(sched.model_id)
        batches = await repo.find(
            Collections.DATASETS,
            Dataset,
            where={"model_id": sched.model_id, "role": "monitoring_batch"},
            page_size=1000,
            order_by="created_at",
        )
        for ds in batches.items:
            if await repo.get_or_none(Collections.METRICS, metric_key(sched.model_id, ds.dataset_id), MonitoringMetric):
                continue
            try:
                metric = await process_batch(sched.model_id, ds.dataset_id)
            except MRFError as exc:
                bucket = "rejected" if exc.code == MRFCode.DATA_QUALITY_FAILED else "failed"
                summary[bucket].append({"batch_id": ds.dataset_id, "code": exc.code.value, "message": exc.message})
                continue
            summary["processed"].append({"batch_id": ds.dataset_id, "status": metric.status})
    return summary


@register_handler("monitoring_batch")
async def run_monitoring_batch(job: Job) -> dict[str, Any]:
    metric = await process_batch(job.payload["model_id"], job.payload["dataset_id"])
    return {"batch_id": metric.batch_id, "status": metric.status, "psi": metric.psi}


@register_handler("monitoring_tick")
async def run_monitoring_tick(job: Job) -> dict[str, Any]:
    return await process_pending(job.payload.get("model_id"))
