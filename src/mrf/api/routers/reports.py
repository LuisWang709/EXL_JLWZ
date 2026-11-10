"""Analysis / validation / monitoring reports.

Owner: A3 (analysis, validation) / A4 (monitoring). Endpoints (see openapi.yaml for request/response schemas):
    GET  /api/v1/models/{model_id}/reports?type=analysis|validation|monitoring   200
    GET  /api/v1/models/{model_id}/reports/{report_id}                           200

``GET .../reports/{report_id}?format=html`` returns the stored HTML artifact itself (additive to contract v1:
the UI can show the report without reading the blob store).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from mrf.api.deps import Paging, ok, paged
from mrf.contracts.models import ModelRecord, Report
from mrf.core import MRFCode, MRFError
from mrf.storage import Collections, get_blobs, get_repo

router = APIRouter(prefix="/models", tags=["reports"])

ReportType = Literal["analysis", "validation", "monitoring", "parity_certificate"]


@router.get("/{model_id}/reports", summary="Reports of a model, newest first")
async def list_reports(
    model_id: str,
    request: Request,
    paging: Paging,
    type: Annotated[ReportType | None, Query()] = None,
) -> JSONResponse:
    repo = get_repo()
    await repo.get(Collections.MODELS, model_id, ModelRecord)
    where: dict[str, Any] = {"model_id": model_id}
    if type:
        where["type"] = type
    page = await repo.find(Collections.REPORTS, Report, where=where, page=paging.page, page_size=paging.page_size)
    return paged(request, page)


@router.get("/{model_id}/reports/{report_id}", summary="Report summary (or the HTML artifact)", response_model=None)
async def get_report(
    model_id: str,
    report_id: str,
    request: Request,
    format: Annotated[Literal["json", "html"], Query()] = "json",
) -> Response:
    report = await get_repo().get(Collections.REPORTS, report_id, Report)
    if report.model_id != model_id:
        raise MRFError(MRFCode.NOT_FOUND, f"report {report_id} does not belong to model {model_id}")
    if format == "html":
        if report.artifact is None:
            raise MRFError(MRFCode.NOT_FOUND, f"report {report_id} has no stored artifact")
        return HTMLResponse((await get_blobs().get_bytes(report.artifact.uri)).decode("utf-8"))
    return ok(request, report)
