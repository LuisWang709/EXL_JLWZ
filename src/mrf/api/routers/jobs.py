"""Status of any async job.

Owner: A1. Endpoints (see openapi.yaml for request/response schemas):
    GET  /api/v1/jobs/{job_id}    200
"""

from fastapi import APIRouter

router = APIRouter(prefix="/jobs", tags=["jobs"])
