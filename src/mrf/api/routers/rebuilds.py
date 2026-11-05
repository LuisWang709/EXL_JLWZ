"""Python rebuild + parity.

Owner: A2. Endpoints (see openapi.yaml for request/response schemas):
    POST /api/v1/models/{model_id}/rebuilds                 202  start a rebuild
    GET  /api/v1/models/{model_id}/rebuilds/{rebuild_id}    200  code, parity result, certificate
"""

from fastapi import APIRouter

router = APIRouter(prefix="/models", tags=["rebuilds"])
