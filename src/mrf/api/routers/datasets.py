"""Dataset registration and quality.

Owner: A2 (register) / A4 (quality). Endpoints (see openapi.yaml for request/response schemas):
    POST /api/v1/datasets                          201  register a dataset reference (any format)
    GET  /api/v1/datasets/{dataset_id}             200  dataset metadata
    GET  /api/v1/datasets/{dataset_id}/quality     200  data quality checks (A4)
"""

from fastapi import APIRouter

router = APIRouter(prefix="/datasets", tags=["datasets"])
