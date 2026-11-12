"""Model runs (usability run or daily batch).

Owner: A2. Endpoints (see openapi.yaml for request/response schemas):
    POST /api/v1/models/{model_id}/runs             202  run the rebuilt model on a dataset
    GET  /api/v1/models/{model_id}/runs             200  runs, newest first
    GET  /api/v1/models/{model_id}/runs/{run_id}    200  run result + metrics
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from mrf.api.deps import IdemKey, Paging, accepted_response, ok, paged
from mrf.contracts.agents import StepContext
from mrf.contracts.models import Dataset, Job, ModelRecord, Run
from mrf.core import MRFCode, MRFError
from mrf.jobs import get_executor, register_handler
from mrf.storage import Collections, get_repo

router = APIRouter(prefix="/models", tags=["runs"])


class RunCreate(BaseModel):
    dataset_id: str
    kind: Literal["usability", "batch"] = "usability"
    reference_dataset_id: str | None = None


@register_handler("model_run")
async def run_model(job: Job) -> dict[str, Any]:
    from mrf.orchestrator.service import get_orchestrator

    repo = get_repo()
    model = await repo.get(Collections.MODELS, job.resource["model_id"], ModelRecord)
    payload = job.payload
    artifacts: dict[str, Any] = {}
    if payload.get("reference_dataset_id"):
        artifacts["reference_dataset_id"] = payload["reference_dataset_id"]
    ctx = StepContext(
        pipeline_id=model.pipeline_id or "",
        model=model,
        source_files=model.source_files,
        dataset_ids=[payload["dataset_id"]],
        artifacts=artifacts,
    )
    runner = (await get_orchestrator()).registry.runner
    run = await runner.run(ctx, payload["dataset_id"], payload.get("kind") or "usability")
    await repo.put(Collections.RUNS, run.run_id, run)
    return {"run_id": run.run_id, "status": run.status}


@router.post("/{model_id}/runs", status_code=202, summary="Run the rebuilt model on a dataset")
async def create_run(model_id: str, body: RunCreate, request: Request, idem: IdemKey = None) -> JSONResponse:
    repo = get_repo()
    await repo.get(Collections.MODELS, model_id, ModelRecord)
    await repo.get(Collections.DATASETS, body.dataset_id, Dataset)
    if body.reference_dataset_id:
        await repo.get(Collections.DATASETS, body.reference_dataset_id, Dataset)
    job, _ = await get_executor().submit(
        "model_run", {"model_id": model_id}, payload=body.model_dump(mode="json"), idempotency_key=idem
    )
    return accepted_response(request, job)


@router.get("/{model_id}/runs", summary="List runs")
async def list_runs(model_id: str, request: Request, paging: Paging) -> JSONResponse:
    repo = get_repo()
    await repo.get(Collections.MODELS, model_id, ModelRecord)
    page = await repo.find(
        Collections.RUNS, Run, where={"model_id": model_id}, page=paging.page, page_size=paging.page_size
    )
    return paged(request, page)


@router.get("/{model_id}/runs/{run_id}", summary="Run result and metrics")
async def get_run(model_id: str, run_id: str, request: Request) -> JSONResponse:
    run = await get_repo().get(Collections.RUNS, run_id, Run)
    if run.model_id != model_id:
        raise MRFError(MRFCode.NOT_FOUND, f"run {run_id} not found for model {model_id}")
    return ok(request, run)
