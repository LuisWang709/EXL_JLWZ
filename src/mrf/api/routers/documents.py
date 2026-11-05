"""Model documentation and its ratings.

Owner: A3. Endpoints (see openapi.yaml for request/response schemas):
    POST /api/v1/models/{model_id}/documents                       202  regenerate documentation
    GET  /api/v1/models/{model_id}/documents                       200  list document versions
    GET  /api/v1/models/{model_id}/documents/{doc_id}              200  content + evidence
    GET  /api/v1/models/{model_id}/documents/{doc_id}/ratings      200  all rating attempts
"""

from fastapi import APIRouter

router = APIRouter(prefix="/models", tags=["documents"])
