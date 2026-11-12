"""Python rebuild + parity.

Owner: A2. Endpoints (see openapi.yaml for request/response schemas):
    POST /api/v1/models/{model_id}/rebuilds                 202  start a rebuild (outside the pipeline)
    GET  /api/v1/models/{model_id}/rebuilds                 200  rebuild attempts, newest first
    GET  /api/v1/models/{model_id}/rebuilds/{rebuild_id}    200  code, parity result, certificate

``GET .../rebuilds/{rebuild_id}?format=code|certificate`` returns the generated Python source (text/x-python) or
the parity certificate (text/html) instead of the JSON envelope.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from mrf.api.deps import IdemKey, Paging, accepted_response, ok, paged
from mrf.contracts.agents import StepContext
from mrf.contracts.models import Job, ModelRecord, Rebuild
from mrf.core import MRFCode, MRFError
from mrf.jobs import get_executor, register_handler
from mrf.storage import Collections, get_blobs, get_repo

router = APIRouter(prefix="/models", tags=["rebuilds"])


class RebuildCreate(BaseModel):
    fixture_id: str | None = Field(default=None, description="parity fixture; default: found from the model")
    max_attempts: int = Field(default=5, ge=1, le=5)


@register_handler("rebuild")
async def run_rebuild(job: Job) -> dict[str, Any]:
    """Rebuild + parity with the retry loop, outside the pipeline. Does not move pipeline state."""
    from mrf.orchestrator.service import get_orchestrator

    repo = get_repo()
    model = await repo.get(Collections.MODELS, job.resource["model_id"], ModelRecord)
    rebuilder = (await get_orchestrator()).registry.rebuilder
    artifacts: dict[str, Any] = {}
    if job.payload.get("fixture_id"):
        artifacts["fixture_id"] = job.payload["fixture_id"]
    feedback: list[str] = []
    attempts = int(job.payload.get("max_attempts") or 5)
    rb: Rebuild | None = None
    for attempt in range(1, attempts + 1):
        ctx = StepContext(
            pipeline_id=model.pipeline_id or "",
            model=model,
            source_files=model.source_files,
            attempt=attempt,
            feedback=feedback,
            artifacts=artifacts,
        )
        rb = await rebuilder.rebuild(ctx)
        rb.attempt = attempt
        await repo.put(Collections.REBUILDS, rb.rebuild_id, rb)
        if rb.parity is not None and rb.parity.passed:
            break
        feedback = rb.feedback or ["parity failed"]
        artifacts = {**artifacts, "rebuild_id": rb.rebuild_id}
    if rb is None:  # max_attempts >= 1, so this cannot happen
        raise MRFError(MRFCode.INTERNAL, "rebuild produced no attempt")
    passed = bool(rb.parity and rb.parity.passed)
    return {"rebuild_id": rb.rebuild_id, "passed": passed, "attempts": rb.attempt}


@router.post("/{model_id}/rebuilds", status_code=202, summary="Start a Python rebuild with parity test")
async def create_rebuild(
    model_id: str, request: Request, body: Annotated[RebuildCreate | None, Body()] = None, idem: IdemKey = None
) -> JSONResponse:
    await get_repo().get(Collections.MODELS, model_id, ModelRecord)
    body = body or RebuildCreate()
    job, _ = await get_executor().submit(
        "rebuild", {"model_id": model_id}, payload=body.model_dump(mode="json"), idempotency_key=idem
    )
    return accepted_response(request, job)


@router.get("/{model_id}/rebuilds", summary="List rebuild attempts")
async def list_rebuilds(model_id: str, request: Request, paging: Paging) -> JSONResponse:
    repo = get_repo()
    await repo.get(Collections.MODELS, model_id, ModelRecord)
    page = await repo.find(
        Collections.REBUILDS, Rebuild, where={"model_id": model_id}, page=paging.page, page_size=paging.page_size
    )
    return paged(request, page)


@router.get(
    "/{model_id}/rebuilds/{rebuild_id}", summary="Rebuild result (or its code / certificate)", response_model=None
)
async def get_rebuild(
    model_id: str,
    rebuild_id: str,
    request: Request,
    format: Annotated[Literal["json", "code", "certificate"], Query()] = "json",
) -> Response:
    rb = await get_repo().get(Collections.REBUILDS, rebuild_id, Rebuild)
    if rb.model_id != model_id:
        raise MRFError(MRFCode.NOT_FOUND, f"rebuild {rebuild_id} not found for model {model_id}")
    if format == "code":
        if rb.code is None:
            raise MRFError(MRFCode.NOT_FOUND, f"rebuild {rebuild_id} has no code")
        return PlainTextResponse((await get_blobs().get_bytes(rb.code.uri)).decode("utf-8"), media_type="text/x-python")
    if format == "certificate":
        if rb.certificate is None:
            raise MRFError(MRFCode.NOT_FOUND, f"rebuild {rebuild_id} has no parity certificate")
        return HTMLResponse((await get_blobs().get_bytes(rb.certificate.uri)).decode("utf-8"))
    return ok(request, rb)
