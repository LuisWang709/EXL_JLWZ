"""Monitoring metrics, alerts, schedules.

Owner: A4. Endpoints (see openapi.yaml for request/response schemas):
    GET  /api/v1/monitoring/models/{model_id}/metrics?from=&to=   200
    GET  /api/v1/monitoring/alerts                                200
    PUT  /api/v1/monitoring/schedules/{model_id}                  200
"""

from fastapi import APIRouter

router = APIRouter(prefix="/monitoring", tags=["monitoring"])
