"""Repository / BlobStore protocols shared by every backend."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel, Field

from mrf.contracts.models import ArtifactRef

T = TypeVar("T", bound=BaseModel)

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_FIELD = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


class Collections:
    """Collection names (one per entity). Use these constants, not string literals."""

    MODELS = "models"
    PIPELINES = "pipelines"
    JOBS = "jobs"
    REVIEWS = "reviews"
    DOCUMENTS = "documents"
    RATINGS = "ratings"
    REBUILDS = "rebuilds"
    DATASETS = "datasets"
    QUALITY = "quality_reports"
    RUNS = "runs"
    REPORTS = "reports"
    ALERTS = "alerts"
    METRICS = "monitoring_metrics"
    SCHEDULES = "schedules"
    AUDIT = "audit"
    IDEMPOTENCY = "idempotency"


class Pagination(BaseModel):
    page: int = 1
    page_size: int = 20
    total: int = 0


class Page(BaseModel, Generic[T]):
    items: list[T] = Field(default_factory=list)
    pagination: Pagination = Field(default_factory=Pagination)


def check_collection(name: str) -> str:
    if not _NAME.match(name):
        raise ValueError(f"invalid collection name {name!r}")
    return name


def check_field(name: str) -> str:
    if not _FIELD.match(name):
        raise ValueError(f"invalid field path {name!r}")
    return name


def to_doc(doc: BaseModel | dict[str, Any]) -> dict[str, Any]:
    return doc.model_dump(mode="json") if isinstance(doc, BaseModel) else dict(doc)


def norm_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def get_path(doc: dict[str, Any], path: str) -> Any:
    cur: Any = doc
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


class Repository(Protocol):
    """JSON-document store. ``where`` = equality filters on (dotted) fields; values may be lists (IN)."""

    async def put(
        self, collection: str, doc_id: str, doc: BaseModel | dict[str, Any], *, if_version: int | None = None
    ) -> int:
        """Insert or replace; returns the new version. ``if_version`` mismatch -> MRF-3201."""
        ...

    async def get(self, collection: str, doc_id: str, model: type[T]) -> T:
        """Raises MRF-1404 when missing."""
        ...

    async def get_or_none(self, collection: str, doc_id: str, model: type[T]) -> T | None: ...

    async def get_version(self, collection: str, doc_id: str) -> int | None: ...

    async def find(
        self,
        collection: str,
        model: type[T],
        *,
        where: dict[str, Any] | None = None,
        page: int = 1,
        page_size: int = 20,
        order_by: str = "-created_at",
    ) -> Page[T]: ...

    async def delete(self, collection: str, doc_id: str) -> bool: ...

    async def close(self) -> None: ...


class BlobStore(Protocol):
    async def put_bytes(
        self, path: str, data: bytes, *, media_type: str = "application/octet-stream", filename: str | None = None
    ) -> ArtifactRef: ...

    async def get_bytes(self, uri: str) -> bytes: ...

    async def exists(self, uri: str) -> bool: ...
