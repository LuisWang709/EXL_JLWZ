"""FastAPI dependencies + response helpers every router uses.

from mrf.api.deps import ApiKey, IdemKey, Paging, accepted_response, ok, created

@router.post("/{model_id}/rebuilds", status_code=202, dependencies=[ApiKey])
async def create_rebuild(model_id: str, body: RebuildCreate, request: Request, idem: IdemKey):
    job, _ = await get_executor().submit("rebuild", {"model_id": model_id},
                                         payload=body.model_dump(mode="json"), idempotency_key=idem)
    return accepted_response(request, job)
"""

from __future__ import annotations

import secrets
from typing import Annotated, Any

from fastapi import Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from mrf.config import get_settings
from mrf.contracts.models import Job
from mrf.core import MRFCode, MRFError, accepted, success
from mrf.storage import Page


async def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().api_key
    if not expected:  # empty key disables auth (never in dev/demo)
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise MRFError(MRFCode.INPUT_BODY, "missing or invalid X-API-Key", field="X-API-Key")


ApiKey = Depends(require_api_key)
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key", max_length=128)]
Operator = Annotated[str, Header(alias="X-Operator", min_length=1, max_length=128)]


class PageParams(BaseModel):
    page: int = 1
    page_size: int = 20


def _paging(page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(ge=1, le=100)] = 20) -> PageParams:
    return PageParams(page=page, page_size=page_size)


Paging = Annotated[PageParams, Depends(_paging)]


def rid(request: Request) -> str:
    return str(request.state.request_id)


def _json(env: BaseModel, status: int) -> JSONResponse:
    return JSONResponse(status_code=status, content=env.model_dump(mode="json"))


def ok(
    request: Request, data: Any = None, *, message: str | None = None, warnings: list[str] | None = None
) -> JSONResponse:
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json")
    return _json(success(rid(request), data, message=message, warnings=warnings), 200)


def created(request: Request, data: Any, *, message: str = "Created") -> JSONResponse:
    if isinstance(data, BaseModel):
        data = data.model_dump(mode="json")
    return _json(success(rid(request), data, message=message), 201)


def paged(request: Request, page: Page[Any]) -> JSONResponse:
    return ok(request, page)


def accepted_response(
    request: Request, job: Job, *, extra: dict[str, Any] | None = None, message: str | None = None
) -> JSONResponse:
    return _json(accepted(rid(request), job.job_id, extra=extra, message=message), 202)
