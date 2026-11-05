"""Pipelines - start the end-to-end flow and read its state.

Owner: A1. Endpoints (see openapi.yaml for request/response schemas):
    POST /api/v1/pipelines                  202  upload code (+dataset refs), start pipeline
    GET  /api/v1/pipelines                  200  list pipelines (paged)
    GET  /api/v1/pipelines/{pipeline_id}    200  state, current step, attempts, history
"""

from fastapi import APIRouter

router = APIRouter(prefix="/pipelines", tags=["pipelines"])
