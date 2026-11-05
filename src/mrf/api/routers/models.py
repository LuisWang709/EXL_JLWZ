"""Model inventory and identification results.

Owner: A1. Endpoints (see openapi.yaml for request/response schemas):
    GET  /api/v1/models                     200  inventory (paged, filter by language/purpose)
    GET  /api/v1/models/{model_id}          200  inventory record + classification
"""

from fastapi import APIRouter

router = APIRouter(prefix="/models", tags=["models"])
