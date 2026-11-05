"""Analysis / validation / monitoring reports.

Owner: A3 (analysis, validation) / A4 (monitoring). Endpoints (see openapi.yaml for request/response schemas):
    GET  /api/v1/models/{model_id}/reports?type=analysis|validation|monitoring   200
    GET  /api/v1/models/{model_id}/reports/{report_id}                           200
"""

from fastapi import APIRouter

router = APIRouter(prefix="/models", tags=["reports"])
