"""Dataset registration and quality.

Owner: A2 (register) / A4 (quality). Endpoints (see openapi.yaml for request/response schemas):
    POST /api/v1/datasets                          201  register a dataset reference (any format)
    GET  /api/v1/datasets/{dataset_id}             200  dataset metadata
    GET  /api/v1/datasets/{dataset_id}/quality     200  data quality checks (A4)
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from mrf.api.deps import ok
from mrf.contracts.models import QualityReport
from mrf.storage import Collections, get_repo

router = APIRouter(prefix="/datasets", tags=["datasets"])


# ---------------------------------------------------------------- A4: quality
@router.get("/{dataset_id}/quality")
async def get_dataset_quality(dataset_id: str, request: Request) -> JSONResponse:
    """Latest quality report; runs the checks now if the dataset was never checked (unknown id -> MRF-1404)."""
    from mrf.monitoring.quality import QualityCheckerImpl

    report = await get_repo().get_or_none(Collections.QUALITY, dataset_id, QualityReport)
    if report is None:
        report = await QualityCheckerImpl().check(dataset_id)
    return ok(request, report)
