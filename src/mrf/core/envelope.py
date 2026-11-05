"""Unified response envelope for every /api/v1 response.

{"request_id", "status": success|accepted|error, "code", "message", "data", "errors": [], "warnings": []}
"""

from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from mrf.core.codes import MRFCode

T = TypeVar("T")

Status = Literal["success", "accepted", "error"]


class ErrorItem(BaseModel):
    code: str
    message: str
    field: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class Envelope(BaseModel, Generic[T]):
    request_id: str
    status: Status
    code: str
    message: str
    data: T | None = None
    errors: list[ErrorItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def success(
    request_id: str,
    data: Any = None,
    *,
    message: str | None = None,
    warnings: list[str] | None = None,
) -> Envelope[Any]:
    return Envelope(
        request_id=request_id,
        status="success",
        code=MRFCode.OK.value,
        message=message or MRFCode.OK.default_message,
        data=data,
        warnings=warnings or [],
    )


def accepted(
    request_id: str,
    job_id: str,
    *,
    message: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Envelope[Any]:
    data: dict[str, Any] = {"job_id": job_id, "poll": f"/api/v1/jobs/{job_id}"}
    data.update(extra or {})
    return Envelope(
        request_id=request_id,
        status="accepted",
        code=MRFCode.ACCEPTED.value,
        message=message or MRFCode.ACCEPTED.default_message,
        data=data,
    )


def error(
    request_id: str,
    code: MRFCode,
    *,
    message: str | None = None,
    errors: list[ErrorItem] | None = None,
    data: Any = None,
) -> Envelope[Any]:
    msg = message or code.default_message
    return Envelope(
        request_id=request_id,
        status="error",
        code=code.value,
        message=msg,
        data=data,
        errors=errors or [ErrorItem(code=code.value, message=msg)],
    )
