"""Register a deployed model for monitoring - implements ``MonitoringRegistrar`` (slot ``monitoring``). Owner: A4.

Called by the orchestrator right after ``deployed``. It
  1. saves the model's ``Schedule`` (cron from the caller, else the existing one, else policy default), and
  2. records the drift baseline on the model's tags (no contract change needed):
       monitoring.baseline_dataset_id  the usability dataset (prefers out_of_time / development / reference)
       monitoring.baseline_run_id      the usability run on that dataset (its scores and Gini are the baseline)
"""

from __future__ import annotations

import logging

from mrf.contracts.agents import StepContext
from mrf.contracts.models import Dataset, ModelRecord, Run, Schedule, utcnow
from mrf.monitoring.drift import thresholds
from mrf.storage import Collections, get_repo

log = logging.getLogger(__name__)

TAG_BASELINE_DATASET = "monitoring.baseline_dataset_id"
TAG_BASELINE_RUN = "monitoring.baseline_run_id"
BASELINE_ROLES = ("out_of_time", "development", "reference", "validation")


async def _baseline_dataset(ctx: StepContext) -> Dataset | None:
    repo = get_repo()
    found = [d for i in ctx.dataset_ids if (d := await repo.get_or_none(Collections.DATASETS, i, Dataset))]
    if not found:
        page = await repo.find(
            Collections.DATASETS, Dataset, where={"model_id": ctx.model.model_id, "role": list(BASELINE_ROLES)}
        )
        found = page.items
    for role in BASELINE_ROLES:
        for d in found:
            if d.role == role:
                return d
    return found[0] if found else None


async def _baseline_run(ctx: StepContext, dataset_id: str) -> Run | None:
    repo = get_repo()
    for run_id in ctx.artifacts.get("run_ids") or []:
        run = await repo.get_or_none(Collections.RUNS, str(run_id), Run)
        if run is not None and run.dataset_id == dataset_id:
            return run
    return None


class MonitoringRegistrarImpl:
    async def register(self, ctx: StepContext, cron: str | None = None) -> None:
        repo = get_repo()
        model_id = ctx.model.model_id
        existing = await repo.get_or_none(Collections.SCHEDULES, model_id, Schedule)
        schedule = Schedule(
            model_id=model_id,
            cron=cron or (existing.cron if existing else str(thresholds()["default_schedule_cron"])),
            enabled=existing.enabled if existing else True,
            report_types=existing.report_types if existing else ["monitoring"],
        )
        await repo.put(Collections.SCHEDULES, model_id, schedule)

        if ctx.artifacts.get("revalidation_dataset_ids"):
            # Approval of a drift investigation must not silently redefine the healthy reference population.
            return

        baseline = await _baseline_dataset(ctx)
        if baseline is None:
            log.warning("monitoring: no registered baseline dataset for %s - drift cannot be computed", model_id)
            return
        model = await repo.get(Collections.MODELS, model_id, ModelRecord)
        tags = {**model.tags, TAG_BASELINE_DATASET: baseline.dataset_id}
        run = await _baseline_run(ctx, baseline.dataset_id)
        if run is not None:
            tags[TAG_BASELINE_RUN] = run.run_id
        model.tags, model.updated_at = tags, utcnow()
        await repo.put(Collections.MODELS, model_id, model)
        log.info("monitoring registered", extra={"model_id": model_id, "cron": schedule.cron, **tags})
