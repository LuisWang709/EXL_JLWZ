"""Model documentation and its ratings.

Owner: A3. Endpoints (see openapi.yaml for request/response schemas):
    POST /api/v1/models/{model_id}/documents                       202  regenerate documentation
    GET  /api/v1/models/{model_id}/documents                       200  list document versions
    GET  /api/v1/models/{model_id}/documents/{doc_id}              200  content + evidence
    GET  /api/v1/models/{model_id}/documents/{doc_id}/ratings      200  all rating attempts

``GET .../documents/{doc_id}?format=markdown|html`` returns the document itself (text/markdown or text/html)
instead of the JSON envelope, so the UI can show or download it directly.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from mrf.api.deps import IdemKey, Paging, accepted_response, ok, paged
from mrf.config import get_policy
from mrf.contracts.agents import StepContext
from mrf.contracts.models import Document, Job, ModelRecord, Pipeline, Rating
from mrf.core import MRFCode, MRFError
from mrf.jobs import get_executor, register_handler
from mrf.reporting.html import html_page, markdown_to_html
from mrf.storage import Collections, get_repo

router = APIRouter(prefix="/models", tags=["documents"])


class DocumentCreate(BaseModel):
    feedback: list[str] = Field(default_factory=list, description="reviewer notes for the first draft")
    rate: bool = Field(default=True, description="rate each draft and redraft on failure (up to the retry limit)")


@register_handler("document")
async def regenerate_document(job: Job) -> dict[str, Any]:
    """Draft (+ rate and redraft with the rater's comments) outside the pipeline. Does not move pipeline state."""
    from mrf.orchestrator.service import get_orchestrator

    repo = get_repo()
    model = await repo.get(Collections.MODELS, job.resource["model_id"], ModelRecord)
    pipeline = await repo.get_or_none(Collections.PIPELINES, model.pipeline_id, Pipeline) if model.pipeline_id else None
    registry = (await get_orchestrator()).registry
    rate = bool(job.payload.get("rate", True))
    feedback = [str(f) for f in job.payload.get("feedback") or []]
    max_attempts = int(get_policy()["retries"]["doc_quality_max_attempts"]) if rate else 1
    result: dict[str, Any] = {"model_id": model.model_id, "attempts": 0, "passed": None}
    for attempt in range(1, max_attempts + 1):
        ctx = StepContext(
            pipeline_id=pipeline.pipeline_id if pipeline else f"adhoc_{job.job_id}",
            model=model,
            source_files=model.source_files,
            dataset_ids=pipeline.dataset_ids if pipeline else [],
            attempt=attempt,
            feedback=feedback,
            artifacts=dict(pipeline.artifacts) if pipeline else {},
        )
        doc = await registry.doc_writer.draft(ctx)
        doc.attempt = attempt
        await repo.put(Collections.DOCUMENTS, doc.doc_id, doc)
        result.update(doc_id=doc.doc_id, attempts=attempt)
        if not rate:
            return result
        rating = await registry.rater.rate(ctx, doc)
        await repo.put(Collections.RATINGS, rating.rating_id, rating)
        doc.status = "rated"
        await repo.put(Collections.DOCUMENTS, doc.doc_id, doc)
        result.update(rating_id=rating.rating_id, total=rating.total, passed=rating.passed, veto=rating.veto_flags)
        if rating.passed:
            break
        feedback = rating.comments or [f"score {rating.total:.0f} below pass"]
    return result


async def _document(model_id: str, doc_id: str) -> Document:
    doc = await get_repo().get(Collections.DOCUMENTS, doc_id, Document)
    if doc.model_id != model_id:
        raise MRFError(MRFCode.NOT_FOUND, f"document {doc_id} does not belong to model {model_id}")
    return doc


@router.post("/{model_id}/documents", status_code=202, summary="Regenerate documentation (draft + rate loop)")
async def create_document(
    model_id: str,
    request: Request,
    body: Annotated[DocumentCreate | None, Body()] = None,
    idem: IdemKey = None,
) -> JSONResponse:
    await get_repo().get(Collections.MODELS, model_id, ModelRecord)  # unknown model -> MRF-1404
    body = body or DocumentCreate()
    job, _ = await get_executor().submit(
        "document", {"model_id": model_id}, payload=body.model_dump(mode="json"), idempotency_key=idem
    )
    return accepted_response(request, job)


@router.get("/{model_id}/documents", summary="Document versions, newest first")
async def list_documents(model_id: str, request: Request, paging: Paging) -> JSONResponse:
    repo = get_repo()
    await repo.get(Collections.MODELS, model_id, ModelRecord)
    page = await repo.find(
        Collections.DOCUMENTS, Document, where={"model_id": model_id}, page=paging.page, page_size=paging.page_size
    )
    return paged(request, page)


@router.get("/{model_id}/documents/{doc_id}", summary="Document content and evidence", response_model=None)
async def get_document(
    model_id: str,
    doc_id: str,
    request: Request,
    format: Annotated[Literal["json", "markdown", "html"], Query()] = "json",
) -> Response:
    doc = await _document(model_id, doc_id)
    if format == "markdown":
        return PlainTextResponse(doc.content_md, media_type="text/markdown; charset=utf-8")
    if format == "html":
        return HTMLResponse(html_page(f"Model documentation {doc.doc_id}", markdown_to_html(doc.content_md)))
    return ok(request, doc)


@router.get("/{model_id}/documents/{doc_id}/ratings", summary="All rating attempts, oldest first")
async def list_ratings(model_id: str, doc_id: str, request: Request) -> JSONResponse:
    doc = await _document(model_id, doc_id)
    page = await get_repo().find(Collections.RATINGS, Rating, where={"doc_id": doc.doc_id}, order_by="attempt")
    return ok(request, {"items": [r.model_dump(mode="json") for r in page.items]})
