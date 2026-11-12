"""Monitoring metrics, alerts, schedules, runs.

Owner: A4. Endpoints (see openapi.yaml for request/response schemas):
    GET  /api/v1/monitoring/models/{model_id}/metrics?from=&to=   200
    GET  /api/v1/monitoring/alerts                                200  (paged)
    PUT  /api/v1/monitoring/schedules/{model_id}                  200  409 MRF-3201 if the model is not deployed
    POST /api/v1/monitoring/runs                                  202  one batch, or every pending batch (timer);
                                                                       report=true also builds a monitoring report
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

import mrf.monitoring.batch  # noqa: F401  registers the monitoring_batch / monitoring_tick job handlers
from mrf.api.deps import IdemKey, Operator, Paging, accepted_response, ok, paged
from mrf.config import get_policy
from mrf.contracts.models import Alert, Dataset, ModelRecord, MonitoringMetric, ReportKind, Schedule, utcnow
from mrf.core import MRFCode, MRFError, guards
from mrf.jobs import get_executor
from mrf.monitoring.cron import Cron
from mrf.storage import Collections, get_repo

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


def _utc(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


@router.get("/models/{model_id}/metrics")
async def get_metrics(
    model_id: str,
    request: Request,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
) -> JSONResponse:
    repo = get_repo()
    await repo.get(Collections.MODELS, model_id, ModelRecord)  # unknown model -> MRF-1404
    start, end = _utc(from_), _utc(to)
    if start is not None and end is not None and start > end:
        raise MRFError(MRFCode.INPUT_BODY, "from must be before or equal to to", field="from")
    page = await repo.find(
        Collections.METRICS, MonitoringMetric, where={"model_id": model_id}, page_size=10_000, order_by="at"
    )
    items = [m for m in page.items if (start is None or m.at >= start) and (end is None or m.at <= end)]
    return ok(request, {"items": [m.model_dump(mode="json") for m in items]})


@router.get("/alerts")
async def list_alerts(
    request: Request,
    paging: Paging,
    model_id: str | None = None,
    severity: Annotated[str | None, Query(pattern="^(amber|red)$")] = None,
    acknowledged: bool | None = None,
    status: Annotated[str | None, Query(pattern="^(open|acknowledged|closed)$")] = None,
) -> JSONResponse:
    where: dict[str, Any] = {}
    if model_id:
        where["model_id"] = model_id
    if severity:
        where["severity"] = severity
    if acknowledged is not None:
        where["acknowledged"] = acknowledged
    if status is not None:
        # Older stored alerts have no status field. Decode them before filtering to preserve compatibility.
        matches: list[Alert] = []
        number = 1
        while True:
            chunk = await get_repo().find(Collections.ALERTS, Alert, where=where or None, page=number, page_size=100)
            matches.extend(a for a in chunk.items if a.status == status)
            if number * 100 >= chunk.pagination.total or not chunk.items:
                break
            number += 1
        offset = (paging.page - 1) * paging.page_size
        return ok(request, {"items": [a.model_dump(mode="json") for a in matches[offset:offset + paging.page_size]],
                            "pagination": {"page": paging.page, "page_size": paging.page_size, "total": len(matches)}})
    page = await get_repo().find(
        Collections.ALERTS, Alert, where=where or None, page=paging.page, page_size=paging.page_size
    )
    return paged(request, page)


class AlertClosure(BaseModel):
    resolution: str = Field(min_length=1, max_length=2000)


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, request: Request, operator: Operator) -> JSONResponse:
    return ok(request, await _act_on_alert(alert_id, operator))


@router.post("/alerts/{alert_id}/close")
async def close_alert(alert_id: str, body: AlertClosure, request: Request, operator: Operator) -> JSONResponse:
    resolution = body.resolution.strip()
    if not resolution:
        raise MRFError(MRFCode.INPUT_BODY, "a resolution is required", field="resolution")
    guards.raise_on(guards.scan_text(resolution, "resolution"), field="resolution")
    return ok(request, await _act_on_alert(alert_id, operator, resolution))


async def _act_on_alert(alert_id: str, operator: str, resolution: str | None = None) -> Alert:
    operator = operator.strip()
    if not operator:
        raise MRFError(MRFCode.INPUT_BODY, "operator is required", field="X-Operator")
    guards.raise_on(guards.scan_text(operator, "X-Operator"), field="X-Operator")
    repo = get_repo()
    version = await repo.get_version(Collections.ALERTS, alert_id)
    alert = await repo.get(Collections.ALERTS, alert_id, Alert)
    if alert.status == "closed" or (alert.acknowledged and resolution is None):
        return alert
    if not alert.acknowledged:
        alert.acknowledged, alert.acknowledged_by, alert.acknowledged_at = True, operator, utcnow()
    alert.status = "acknowledged"
    if resolution is not None:
        alert.status, alert.closed_by, alert.closed_at, alert.resolution = "closed", operator, utcnow(), resolution
    await repo.put(Collections.ALERTS, alert_id, alert, if_version=version)
    return alert


class ScheduleIn(BaseModel):
    cron: str = Field(examples=["0 6 * * 1", "0 * * * *"])
    enabled: bool = True
    report_types: list[ReportKind] = Field(default_factory=lambda: ["monitoring"])  # type: ignore[arg-type]

    @field_validator("cron")
    @classmethod
    def _five_fields(cls, value: str) -> str:
        Cron(value)
        return value.strip()


@router.put("/schedules/{model_id}")
async def put_schedule(model_id: str, body: ScheduleIn, request: Request) -> JSONResponse:
    repo = get_repo()
    model = await repo.get(Collections.MODELS, model_id, ModelRecord)
    if model.lifecycle != "production":
        raise MRFError(
            MRFCode.INVALID_STATE,
            "monitoring schedules apply to deployed models",
            detail={"lifecycle": model.lifecycle},
        )
    schedule = Schedule(model_id=model_id, **body.model_dump())
    await repo.put(Collections.SCHEDULES, model_id, schedule)
    return ok(request, schedule)


@router.get("/schedules/{model_id}")
async def get_schedule(model_id: str, request: Request) -> JSONResponse:
    from mrf.monitoring.registrar import TAG_BASELINE_DATASET, TAG_BASELINE_RUN

    repo = get_repo()
    model = await repo.get(Collections.MODELS, model_id, ModelRecord)
    schedule = await repo.get_or_none(Collections.SCHEDULES, model_id, Schedule)
    policy = get_policy()["monitoring"]
    current = schedule or Schedule(model_id=model_id, cron=policy["default_schedule_cron"], enabled=False)
    return ok(request, {
        **current.model_dump(mode="json"), "configured": schedule is not None,
        "baseline_dataset_id": model.tags.get(TAG_BASELINE_DATASET),
        "baseline_run_id": model.tags.get(TAG_BASELINE_RUN),
        "thresholds": {k: policy[k] for k in (
            "psi_amber", "psi_red", "gini_drop_red", "min_rows", "missing_rate_amber", "missing_rate_red",
        )},
    })


class MonitoringRunIn(BaseModel):
    model_id: str | None = Field(default=None, description="limit to one model; omit = every enabled schedule")
    dataset_id: str | None = Field(default=None, description="process this one batch (needs model_id)")
    report: bool = Field(default=False, description="also build a monitoring report now")


@router.post("/runs", status_code=202)
async def start_monitoring_run(
    request: Request,
    body: Annotated[MonitoringRunIn | None, Body()] = None,
    idem: IdemKey = None,
) -> JSONResponse:
    body = body or MonitoringRunIn()
    repo = get_repo()
    if body.model_id:
        await repo.get(Collections.MODELS, body.model_id, ModelRecord)
    if body.dataset_id:
        if not body.model_id:
            raise MRFError(MRFCode.INPUT_BODY, "dataset_id requires model_id", field="model_id")
        await repo.get(Collections.DATASETS, body.dataset_id, Dataset)
        job, _ = await get_executor().submit(
            "monitoring_batch",
            {"model_id": body.model_id},
            payload=body.model_dump(mode="json"),
            idempotency_key=idem,
        )
    else:
        resource = {"model_id": body.model_id} if body.model_id else {}
        job, _ = await get_executor().submit(
            "monitoring_tick", resource, payload=body.model_dump(mode="json"), idempotency_key=idem
        )
    return accepted_response(request, job)
