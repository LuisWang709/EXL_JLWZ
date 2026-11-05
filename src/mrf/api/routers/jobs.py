"""Status of any async job. Owner: A1.

GET  /api/v1/jobs/{job_id}    200
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from mrf.api.deps import ok
from mrf.contracts.models import Job
from mrf.storage import Collections, get_repo

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", summary="Job status, result or error")
async def get_job(job_id: str, request: Request) -> JSONResponse:
    return ok(request, await get_repo().get(Collections.JOBS, job_id, Job))
