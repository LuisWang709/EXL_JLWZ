"""Model runs (usability run or daily batch).

Owner: A2. Endpoints (see openapi.yaml for request/response schemas):
    POST /api/v1/models/{model_id}/runs             202  run rebuilt model on a dataset
    GET  /api/v1/models/{model_id}/runs/{run_id}    200  run result + metrics
"""

from fastapi import APIRouter

router = APIRouter(prefix="/models", tags=["runs"])
