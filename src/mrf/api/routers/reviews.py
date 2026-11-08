"""Human review queue: H1, H2 and manual-review items. Owner: A1.

GET  /api/v1/reviews?status=pending&gate=H1          200
GET  /api/v1/reviews/{review_id}                     200
POST /api/v1/reviews/{review_id}/decision            200  approve | reject | edit -> resumes pipeline
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from mrf.api.deps import Operator, Paging, ok, paged
from mrf.contracts.models import Gate, Review, ReviewDecision
from mrf.orchestrator.service import decide_review
from mrf.storage import Collections, get_repo

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("", summary="Review queue")
async def list_reviews(
    request: Request,
    paging: Paging,
    status: Literal["pending", "approved", "rejected", "edited"] | None = None,
    gate: Gate | None = None,
) -> JSONResponse:
    where: dict[str, Any] = {}
    if status:
        where["status"] = status
    if gate:
        where["gate"] = gate.value
    page = await get_repo().find(
        Collections.REVIEWS, Review, where=where or None, page=paging.page, page_size=paging.page_size
    )
    return paged(request, page)


@router.get("/{review_id}", summary="One review item")
async def get_review(review_id: str, request: Request) -> JSONResponse:
    return ok(request, await get_repo().get(Collections.REVIEWS, review_id, Review))


@router.post("/{review_id}/decision", summary="Approve / reject / edit and resume the pipeline")
async def decide(review_id: str, body: ReviewDecision, request: Request, operator: Operator) -> JSONResponse:
    review, job = await decide_review(review_id, body, operator)
    return ok(
        request,
        {"review": review.model_dump(mode="json"), "job_id": job.job_id, "poll": f"/api/v1/jobs/{job.job_id}"},
        message="Decision recorded",
    )
