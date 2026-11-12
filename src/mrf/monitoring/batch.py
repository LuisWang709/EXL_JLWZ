"""One monitoring batch end to end, plus the job handlers. Owner: A4.

    quality check -> ModelRunner.run(kind="batch") -> PSI/CSI vs the baseline -> MonitoringMetric
    -> amber/red Alert -> on red: trigger_revalidation (pipeline goes back to usability_run)

After the batches of a schedule, a monitoring report (mrf.monitoring.report) is built when new batches were
processed or the schedule's cron fired since the last report; ``report: true`` in the job payload forces one.

Runs inside the API process as a job (``monitoring_batch`` / ``monitoring_tick``): business data and the job
queue live there, so a separate container could not see them. The Container Apps Job only calls
``POST /api/v1/monitoring/runs`` on a timer.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from weakref import WeakKeyDictionary

from mrf.contracts.agents import ModelRunner, StepContext
from mrf.contracts.models import (
    Alert,
    Dataset,
    Job,
    ModelRecord,
    MonitoringMetric,
    QualityCheck,
    Report,
    Run,
    Schedule,
)
from mrf.core import MRFCode, MRFError
from mrf.jobs import register_handler
from mrf.monitoring.cron import fired_between
from mrf.monitoring.drift import classify, compute_psi, pick_features
from mrf.monitoring.frames import frame_scope, load_frame, run_scores
from mrf.monitoring.quality import QualityCheckerImpl
from mrf.monitoring.registrar import TAG_BASELINE_DATASET, TAG_BASELINE_RUN
from mrf.monitoring.report import generate as generate_report
from mrf.storage import Collections, get_repo

log = logging.getLogger(__name__)
_locks: WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]] = WeakKeyDictionary()


def metric_key(model_id: str, dataset_id: str) -> str:
    return f"{model_id}:{dataset_id}"


def _runner() -> ModelRunner:
    from mrf.agents.rebuild.runner import ModelRunnerImpl

    return ModelRunnerImpl()


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _missing_by_column(checks: list[QualityCheck]) -> dict[str, float]:
    found = next((c.detail.get("by_column") for c in checks if c.name == "missing_rate"), None)
    return {str(k): float(v) for k, v in (found or {}).items()}


async def _alert(model_id: str, severity: str, kind: str, message: str, detail: dict[str, Any]) -> Alert:
    key = f"{model_id}:{detail.get('batch_id')}:{kind}"
    alert_id = "alert_" + hashlib.sha256(key.encode()).hexdigest()[:24]
    existing = await get_repo().get_or_none(Collections.ALERTS, alert_id, Alert)
    if existing is not None:
        return existing
    alert = Alert(
        alert_id=alert_id,
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


async def _revalidate(model_id: str, dataset_id: str, reasons: list[str]) -> str | None:
    """Job id of the re-validation, or None if the pipeline is not in ``monitoring`` (already re-validating)."""
    from mrf.orchestrator.service import trigger_revalidation

    try:
        job = await trigger_revalidation(
            model_id, reason="; ".join(reasons) or "drift above threshold", dataset_id=dataset_id
        )
    except MRFError as exc:
        if exc.code != MRFCode.INVALID_STATE:
            raise
        log.info("monitoring: re-validation not triggered for %s: %s", model_id, exc.message)
        return None
    return job.job_id


async def process_batch(model_id: str, dataset_id: str) -> MonitoringMetric:
    model_locks = _locks.setdefault(asyncio.get_running_loop(), {})
    async with model_locks.setdefault(model_id, asyncio.Lock()):
        with frame_scope():
            try:
                return await _process_batch(model_id, dataset_id)
            except MRFError as exc:
                if exc.code not in {MRFCode.DATA_QUALITY_FAILED, MRFCode.NOT_FOUND, MRFCode.INPUT_BODY}:
                    await _alert(model_id, "red", "system", "Monitoring could not complete: " + exc.message,
                                 {"batch_id": dataset_id, "code": exc.code.value})
                raise
            except Exception:
                await _alert(model_id, "red", "system", "Monitoring failed unexpectedly; inspect the task error.",
                             {"batch_id": dataset_id, "code": MRFCode.INTERNAL.value})
                raise


async def _process_batch(model_id: str, dataset_id: str) -> MonitoringMetric:
    repo = get_repo()
    model = await repo.get(Collections.MODELS, model_id, ModelRecord)
    ds = await repo.get(Collections.DATASETS, dataset_id, Dataset)
    if ds.model_id != model_id or ds.role != "monitoring_batch":
        raise MRFError(MRFCode.INPUT_BODY, "select a monitoring batch associated with this model", field="dataset_id")
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
        await _alert(model_id, "red", "data_quality", f"batch {dataset_id} rejected: {', '.join(failed)}", rejection)
        await repo.put(Collections.METRICS, key, rejected)
        raise MRFError(MRFCode.DATA_QUALITY_FAILED, f"batch {dataset_id} failed: {', '.join(failed)}", detail=rejection)

    # 2. score the batch with the rebuilt model (A2)
    baseline_id = model.tags.get(TAG_BASELINE_DATASET)
    if not baseline_id:
        await _alert(model_id, "red", "system", "Monitoring baseline is missing; configure it before processing.",
                     {"batch_id": dataset_id})
        raise MRFError(MRFCode.INVALID_STATE, f"{model_id} has no monitoring baseline - is it registered?")
    baseline = await repo.get_or_none(Collections.DATASETS, baseline_id, Dataset)
    if baseline is None:
        raise MRFError(MRFCode.INVALID_STATE, f"monitoring baseline dataset {baseline_id} is unavailable")
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
    baseline_run = await repo.get_or_none(Collections.RUNS, baseline_run_id, Run) if baseline_run_id else None
    base_df, batch_df = await asyncio.gather(asyncio.to_thread(load_frame, baseline), asyncio.to_thread(load_frame, ds))
    features = pick_features(model, baseline, base_df, batch_df)
    reported = _number(run.metrics.get("psi_score"))
    if reported is not None:
        psi = await asyncio.to_thread(compute_psi, base_df, batch_df, features)
        psi["__score__"] = reported
    else:  # retain support for runners which provide scores but do not compute PSI
        base_scores, batch_scores = await asyncio.gather(
            asyncio.to_thread(run_scores, baseline_run), asyncio.to_thread(run_scores, run)
        )
        psi = await asyncio.to_thread(compute_psi, base_df, batch_df, features, base_scores, batch_scores)

    gini = _number(run.metrics.get("gini"))
    baseline_gini = _number(baseline_run.metrics.get("gini")) if baseline_run else None
    status, reasons = classify(psi, gini, baseline_gini)
    if not psi and (gini is None or baseline_gini is None):
        status = "amber"
        reasons.append("No comparable drift or performance evidence is available; monitoring is unassessed.")
    quality_warnings = [c.name for c in quality.checks if c.severity == "amber"]
    if quality_warnings:
        if status == "green":
            status = "amber"
        await _alert(model_id, "amber", "data_quality", "Quality warnings: " + ", ".join(quality_warnings),
                     {"batch_id": dataset_id, "checks": quality_warnings})

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
    if reasons:
        detail: dict[str, Any] = {"batch_id": dataset_id, "run_id": run.run_id, "psi": metric.psi, "gini": gini}
        if status == "red":
            detail["revalidation_job_id"] = await _revalidate(model_id, dataset_id, reasons)
        await _alert(model_id, status, "drift", "; ".join(reasons), detail)
    await repo.put(Collections.METRICS, key, metric)
    log.info(
        "monitoring batch",
        extra={"model_id": model_id, "batch_id": dataset_id, "status": status, "max_psi": max(psi.values(), default=0)},
    )
    return metric


async def report_due(schedule: Schedule, new_batches: bool, now: datetime | None = None) -> bool:
    """New batches since the last tick, or the schedule's cron fired since the last monitoring report
    (no report yet: since one hour ago, the timer interval)."""
    if "monitoring" not in schedule.report_types:
        return False
    if new_batches:
        return True
    now = now or datetime.now(UTC)
    last = await get_repo().find(
        Collections.REPORTS,
        Report,
        where={"model_id": schedule.model_id, "type": "monitoring"},
        page_size=1,
        order_by="-created_at",
    )
    start = last.items[0].created_at if last.items else now - timedelta(hours=1)
    try:
        return fired_between(schedule.cron, start, now)
    except ValueError as exc:
        log.warning("monitoring: bad cron %r for %s: %s", schedule.cron, schedule.model_id, exc)
        return False


async def _report(summary: dict[str, Any], model_id: str) -> None:
    try:
        report = await generate_report(model_id)
    except MRFError as exc:
        summary["failed"].append({"report_for": model_id, "code": exc.code.value, "message": exc.message})
        return
    summary["reports"].append({"model_id": model_id, "report_id": report.report_id, "status": report.rag_status})


async def process_pending(model_id: str | None = None, force_report: bool = False) -> dict[str, Any]:
    """Every not-yet-processed ``monitoring_batch`` dataset of every enabled schedule (or of one model), then the
    monitoring reports that are due (or, with ``force_report``, one per schedule)."""
    repo = get_repo()
    where: dict[str, Any] = {"enabled": True}
    if model_id:
        where["model_id"] = model_id
    schedules = await repo.find(Collections.SCHEDULES, Schedule, where=where, page_size=1000, order_by="model_id")
    summary: dict[str, Any] = {"models": [], "processed": [], "rejected": [], "failed": [], "reports": []}
    for sched in schedules.items:
        summary["models"].append(sched.model_id)
        # Older red batches remain actionable while H2 is pending. Submit them on a later tick once
        # the previous investigation is complete; never replace an in-progress human sign-off.
        model_locks = _locks.setdefault(asyncio.get_running_loop(), {})
        async with model_locks.setdefault(sched.model_id, asyncio.Lock()):
            await _retry_revalidations(sched.model_id)
        batches = await repo.find(
            Collections.DATASETS,
            Dataset,
            where={"model_id": sched.model_id, "role": "monitoring_batch"},
            page_size=1000,
            order_by="created_at",
        )
        new_batches = False
        for ds in batches.items:
            if await repo.get_or_none(Collections.METRICS, metric_key(sched.model_id, ds.dataset_id), MonitoringMetric):
                continue
            new_batches = True  # a rejected batch is recorded too and belongs in the report
            try:
                metric = await process_batch(sched.model_id, ds.dataset_id)
            except MRFError as exc:
                bucket = "rejected" if exc.code == MRFCode.DATA_QUALITY_FAILED else "failed"
                summary[bucket].append({"batch_id": ds.dataset_id, "code": exc.code.value, "message": exc.message})
                continue
            summary["processed"].append({"batch_id": ds.dataset_id, "status": metric.status})
        if (force_report and "monitoring" in sched.report_types) or await report_due(sched, new_batches):
            await _report(summary, sched.model_id)
    return summary


async def _retry_revalidations(model_id: str) -> None:
    repo = get_repo()
    page = 1
    while True:
        alerts = await repo.find(
            Collections.ALERTS, Alert, where={"model_id": model_id, "kind": "drift", "severity": "red"},
            page=page, page_size=100, order_by="created_at",
        )
        for alert in alerts.items:
            batch_id = alert.detail.get("batch_id")
            if alert.status == "closed" or alert.detail.get("revalidation_job_id") or not batch_id:
                continue
            job_id = await _revalidate(model_id, batch_id, [alert.message])
            if job_id is None:
                return  # an existing job / H2 must finish first
            version = await repo.get_version(Collections.ALERTS, alert.alert_id)
            # Preserve any acknowledgement made while revalidation was submitted.
            current = await repo.get(Collections.ALERTS, alert.alert_id, Alert)
            current.detail["revalidation_job_id"] = job_id
            await repo.put(Collections.ALERTS, current.alert_id, current, if_version=version)
        if page * 100 >= alerts.pagination.total or not alerts.items:
            return
        page += 1


@register_handler("monitoring_batch")
async def run_monitoring_batch(job: Job) -> dict[str, Any]:
    metric = await process_batch(job.payload["model_id"], job.payload["dataset_id"])
    result: dict[str, Any] = {"batch_id": metric.batch_id, "status": metric.status, "psi": metric.psi}
    if job.payload.get("report"):
        report = await generate_report(metric.model_id)
        result["report_id"] = report.report_id
    return result


@register_handler("monitoring_tick")
async def run_monitoring_tick(job: Job) -> dict[str, Any]:
    model_id, force = job.payload.get("model_id"), bool(job.payload.get("report"))
    summary = await process_pending(model_id, force_report=force)
    if force and model_id and not any(r["model_id"] == model_id for r in summary["reports"]):
        await _report(summary, model_id)  # no enabled schedule (model not deployed yet): report on request anyway
    return summary
