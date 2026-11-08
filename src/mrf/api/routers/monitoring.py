"""Monitoring metrics, alerts, schedules, runs.

Owner: A4. Endpoints (see openapi.yaml for request/response schemas):
    GET  /api/v1/monitoring/models/{model_id}/metrics?from=&to=   200
    GET  /api/v1/monitoring/alerts                                200  (paged)
    PUT  /api/v1/monitoring/schedules/{model_id}                  200  409 MRF-3201 if the model is not deployed
    POST /api/v1/monitoring/runs                                  202  one batch, or every pending batch (timer)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

import mrf.monitoring.batch  # noqa: F401  registers the monitoring_batch / monitoring_tick job handlers
from mrf.api.deps import IdemKey, Paging, accepted_response, ok, paged
from mrf.contracts.models import Alert, Dataset, ModelRecord, MonitoringMetric, ReportKind, Schedule
from mrf.core import MRFCode, MRFError
from mrf.jobs import get_executor
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
) -> JSONResponse:
    where: dict[str, Any] = {}
    if model_id:
        where["model_id"] = model_id
    if severity:
        where["severity"] = severity
    if acknowledged is not None:
        where["acknowledged"] = acknowledged
    page = await get_repo().find(
        Collections.ALERTS, Alert, where=where or None, page=paging.page, page_size=paging.page_size
    )
    return paged(request, page)


class ScheduleIn(BaseModel):
    cron: str = Field(examples=["0 6 * * 1", "0 * * * *"])
    enabled: bool = True
    report_types: list[ReportKind] = Field(default_factory=lambda: ["monitoring"])  # type: ignore[arg-type]

    @field_validator("cron")
    @classmethod
    def _five_fields(cls, value: str) -> str:
        if len(value.split()) != 5:
            raise ValueError("cron must have 5 fields: minute hour day-of-month month day-of-week (UTC)")
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


class MonitoringRunIn(BaseModel):
    model_id: str | None = Field(default=None, description="limit to one model; omit = every enabled schedule")
    dataset_id: str | None = Field(default=None, description="process this one batch (needs model_id)")


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
