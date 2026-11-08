"""Model inventory and identification results. Owner: A1.

GET  /api/v1/models                     200  inventory (paged, filter by language/purpose/needs_review)
GET  /api/v1/models/{model_id}          200  inventory record + classification
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from mrf.api.deps import Paging, ok, paged
from mrf.contracts.models import ModelRecord
from mrf.storage import Collections, get_repo

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", summary="Model inventory")
async def list_models(
    request: Request,
    paging: Paging,
    language: str | None = None,
    purpose: str | None = None,
    needs_review: bool | None = None,
) -> JSONResponse:
    where: dict[str, Any] = {}
    if language:
        where["classification.language"] = language
    if purpose:
        where["classification.purpose"] = purpose
    if needs_review is not None:
        where["classification.needs_review"] = needs_review
    page = await get_repo().find(
        Collections.MODELS, ModelRecord, where=where or None, page=paging.page, page_size=paging.page_size
    )
    return paged(request, page)


@router.get("/{model_id}", summary="Inventory record with classification and evidence")
async def get_model(model_id: str, request: Request) -> JSONResponse:
    return ok(request, await get_repo().get(Collections.MODELS, model_id, ModelRecord))
