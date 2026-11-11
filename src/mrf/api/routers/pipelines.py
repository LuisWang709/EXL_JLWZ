"""Pipelines - start the end-to-end flow and read its state. Owner: A1.

POST /api/v1/pipelines                  202  upload code (+dataset refs), start pipeline
GET  /api/v1/pipelines                  200  list pipelines (paged)
GET  /api/v1/pipelines/{pipeline_id}    200  state, current step, attempts, history
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from mrf.api.deps import IdemKey, Paging, accepted_response, ok, paged
from mrf.contracts.models import ArtifactRef, Pipeline
from mrf.core import MRFCode, MRFError, PipelineState
from mrf.jobs import body_hash, get_executor
from mrf.orchestrator.service import UploadedFile, create_pipeline, screen_source_refs
from mrf.storage import Collections, get_repo

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


class PipelineOptions(BaseModel):
    rebuild: bool = True
    auto_approve: bool = Field(default=False, description="local demo only; ignored unless MRF_ENV=local")
    language_hint: str | None = None


class PipelineCreate(BaseModel):
    model_name: str = Field(min_length=1, max_length=200)
    source_files: list[ArtifactRef] = Field(min_length=1)
    owner: str | None = None
    description: str | None = None
    dataset_ids: list[str] = Field(default_factory=list)
    options: PipelineOptions = Field(default_factory=PipelineOptions)


async def _start(
    request: Request, idem: str | None, fingerprint: dict[str, Any], options: PipelineOptions, **create_kwargs: Any
) -> JSONResponse:
    executor = get_executor()
    digest = body_hash(fingerprint)
    if idem and (job := await executor.lookup_idempotent("pipeline", idem, digest)) is not None:
        pipeline = await get_repo().get(Collections.PIPELINES, job.resource["pipeline_id"], Pipeline)
        return accepted_response(
            request,
            job,
            message="Pipeline already started",
            extra={"pipeline_id": pipeline.pipeline_id, "model_id": pipeline.model_id},
        )
    pipeline, model = await create_pipeline(**create_kwargs)
    job, _ = await executor.submit(
        "pipeline", {"pipeline_id": pipeline.pipeline_id}, payload={"auto_approve": options.auto_approve}
    )
    if idem:
        await executor.remember_idempotent("pipeline", idem, digest, job.job_id)
    return accepted_response(
        request,
        job,
        message="Pipeline started",
        extra={"pipeline_id": pipeline.pipeline_id, "model_id": model.model_id},
    )


@router.post(
    "",
    status_code=202,
    summary="Upload model code and start the pipeline",
    description="multipart/form-data: files[], model_name, owner?, description?, dataset_ids[]?, options? (JSON); "
    "or application/json PipelineCreate with already-stored source_files.",
)
async def create(request: Request, idem: IdemKey = None) -> JSONResponse:
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("application/json"):
        try:
            body = PipelineCreate.model_validate(await request.json())
        except (ValidationError, json.JSONDecodeError) as exc:
            raise MRFError(
                MRFCode.INPUT_BODY, "invalid PipelineCreate body", detail={"errors": str(exc)[:1000]}
            ) from exc
        await screen_source_refs(body.source_files)
        return await _start(
            request,
            idem,
            body.model_dump(mode="json"),
            body.options,
            model_name=body.model_name,
            source_refs=body.source_files,
            owner=body.owner,
            description=body.description,
            dataset_ids=body.dataset_ids,
        )
    if not ctype.startswith("multipart/form-data"):
        raise MRFError(MRFCode.INPUT_BODY, "use multipart/form-data (files) or application/json (source_files)")

    form = await request.form()
    model_name = str(form.get("model_name") or "").strip()
    if not model_name:
        raise MRFError(MRFCode.INPUT_BODY, "model_name is required", field="model_name")
    uploads = [f for f in form.getlist("files") if not isinstance(f, str)]
    if not uploads:
        raise MRFError(MRFCode.INPUT_BODY, "at least one file is required", field="files")
    try:
        options = PipelineOptions.model_validate_json(str(form.get("options") or "{}"))
    except ValidationError as exc:
        raise MRFError(MRFCode.INPUT_BODY, "options must be a JSON PipelineOptions object", field="options") from exc
    files = [UploadedFile(f.filename or "upload", await f.read(), f.content_type) for f in uploads]
    dataset_ids = [str(d) for d in form.getlist("dataset_ids") if str(d)]
    fingerprint = {
        "model_name": model_name,
        "files": sorted((f.filename, body_hash(f.data.hex())) for f in files),
        "dataset_ids": dataset_ids,
        "options": options.model_dump(),
    }
    return await _start(
        request,
        idem,
        fingerprint,
        options,
        model_name=model_name,
        files=files,
        owner=str(form.get("owner") or "") or None,
        description=str(form.get("description") or "") or None,
        dataset_ids=dataset_ids,
    )


@router.get("", summary="List pipelines")
async def list_pipelines(request: Request, paging: Paging, state: PipelineState | None = None) -> JSONResponse:
    where = {"state": state.value} if state else None
    page = await get_repo().find(
        Collections.PIPELINES, Pipeline, where=where, page=paging.page, page_size=paging.page_size
    )
    return paged(request, page)


@router.get("/{pipeline_id}", summary="Pipeline state, attempts and history")
async def get_pipeline(pipeline_id: str, request: Request) -> JSONResponse:
    return ok(request, await get_repo().get(Collections.PIPELINES, pipeline_id, Pipeline))
