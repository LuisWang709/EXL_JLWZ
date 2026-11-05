"""In-memory repository - unit tests and quick local experiments."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from mrf.core import MRFCode, MRFError
from mrf.storage.base import Page, Pagination, T, check_collection, check_field, get_path, norm_value, to_doc


def _matches(doc: dict[str, Any], where: dict[str, Any]) -> bool:
    for key, expected in where.items():
        actual = get_path(doc, check_field(key))
        if isinstance(expected, list | tuple | set):
            if actual not in {norm_value(v) for v in expected}:
                return False
        elif actual != norm_value(expected):
            return False
    return True


class MemoryRepository:
    def __init__(self) -> None:
        # collection -> id -> (version, created_at, doc)
        self._data: dict[str, dict[str, tuple[int, str, dict[str, Any]]]] = {}
        self._lock = asyncio.Lock()

    async def put(
        self, collection: str, doc_id: str, doc: BaseModel | dict[str, Any], *, if_version: int | None = None
    ) -> int:
        coll = self._data.setdefault(check_collection(collection), {})
        async with self._lock:
            current = coll.get(doc_id)
            cur_version = current[0] if current else 0
            if if_version is not None and if_version != cur_version:
                raise MRFError(
                    MRFCode.INVALID_STATE,
                    f"{collection}/{doc_id} was modified concurrently",
                    detail={"expected_version": if_version, "actual_version": cur_version},
                )
            created = current[1] if current else datetime.now(UTC).isoformat()
            coll[doc_id] = (cur_version + 1, created, to_doc(doc))
            return cur_version + 1

    async def get(self, collection: str, doc_id: str, model: type[T]) -> T:
        found = await self.get_or_none(collection, doc_id, model)
        if found is None:
            raise MRFError(MRFCode.NOT_FOUND, f"{collection}/{doc_id} not found")
        return found

    async def get_or_none(self, collection: str, doc_id: str, model: type[T]) -> T | None:
        row = self._data.get(check_collection(collection), {}).get(doc_id)
        return model.model_validate(row[2]) if row else None

    async def get_version(self, collection: str, doc_id: str) -> int | None:
        row = self._data.get(check_collection(collection), {}).get(doc_id)
        return row[0] if row else None

    async def find(
        self,
        collection: str,
        model: type[T],
        *,
        where: dict[str, Any] | None = None,
        page: int = 1,
        page_size: int = 20,
        order_by: str = "-created_at",
    ) -> Page[T]:
        rows = list(self._data.get(check_collection(collection), {}).values())
        for key in where or {}:
            check_field(key)
        if where:
            rows = [r for r in rows if _matches(r[2], where)]
        desc = order_by.startswith("-")
        key = check_field(order_by.lstrip("-+"))
        if key == "created_at":
            rows.sort(key=lambda r: str(r[2].get("created_at") or r[1]), reverse=desc)
        else:
            rows.sort(key=lambda r: (get_path(r[2], key) is None, str(get_path(r[2], key))), reverse=desc)
        total = len(rows)
        start = (max(page, 1) - 1) * page_size
        items = [model.model_validate(r[2]) for r in rows[start : start + page_size]]
        return Page[model](items=items, pagination=Pagination(page=page, page_size=page_size, total=total))  # type: ignore[valid-type]

    async def delete(self, collection: str, doc_id: str) -> bool:
        return self._data.get(check_collection(collection), {}).pop(doc_id, None) is not None

    async def close(self) -> None:
        return None
