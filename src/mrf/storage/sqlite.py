"""SQLite document store: one table per collection, JSON in a TEXT column, json_extract for filters."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
from pydantic import BaseModel

from mrf.core import MRFCode, MRFError
from mrf.storage.base import Page, Pagination, T, check_collection, check_field, norm_value, to_doc


class SqliteRepository:
    def __init__(self, path: str | Path, journal_mode: str = "WAL") -> None:
        if journal_mode.upper() not in {"WAL", "DELETE", "TRUNCATE"}:
            raise ValueError(f"unsupported journal_mode {journal_mode!r}")
        self.path = str(path)
        self.journal_mode = journal_mode.upper()
        self._conn: aiosqlite.Connection | None = None
        self._tables: set[str] = set()
        self._lock = asyncio.Lock()

    async def _db(self) -> aiosqlite.Connection:
        if self._conn is None:
            if self.path != ":memory:":
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(self.path)
            await self._conn.execute(f"PRAGMA journal_mode={self.journal_mode}")
        return self._conn

    async def _table(self, collection: str) -> str:
        name = check_collection(collection)
        if name not in self._tables:
            db = await self._db()
            await db.execute(
                f'CREATE TABLE IF NOT EXISTS "{name}" ('
                "id TEXT PRIMARY KEY, data TEXT NOT NULL, version INTEGER NOT NULL, "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            await db.commit()
            self._tables.add(name)
        return name

    async def put(
        self, collection: str, doc_id: str, doc: BaseModel | dict[str, Any], *, if_version: int | None = None
    ) -> int:
        table = await self._table(collection)
        db = await self._db()
        now = datetime.now(UTC).isoformat()
        payload = json.dumps(to_doc(doc), default=str)
        async with self._lock:
            async with db.execute(f'SELECT version FROM "{table}" WHERE id = ?', (doc_id,)) as cur:  # noqa: S608
                row = await cur.fetchone()
            current = int(row[0]) if row else 0
            if if_version is not None and if_version != current:
                raise MRFError(
                    MRFCode.INVALID_STATE,
                    f"{collection}/{doc_id} was modified concurrently",
                    detail={"expected_version": if_version, "actual_version": current},
                )
            if row:
                await db.execute(
                    f'UPDATE "{table}" SET data = ?, version = ?, updated_at = ? WHERE id = ?',  # noqa: S608
                    (payload, current + 1, now, doc_id),
                )
            else:
                await db.execute(
                    f'INSERT INTO "{table}" (id, data, version, created_at, updated_at) VALUES (?, ?, 1, ?, ?)',  # noqa: S608
                    (doc_id, payload, now, now),
                )
            await db.commit()
        return current + 1

    async def get(self, collection: str, doc_id: str, model: type[T]) -> T:
        found = await self.get_or_none(collection, doc_id, model)
        if found is None:
            raise MRFError(MRFCode.NOT_FOUND, f"{collection}/{doc_id} not found")
        return found

    async def get_or_none(self, collection: str, doc_id: str, model: type[T]) -> T | None:
        table = await self._table(collection)
        db = await self._db()
        async with db.execute(f'SELECT data FROM "{table}" WHERE id = ?', (doc_id,)) as cur:  # noqa: S608
            row = await cur.fetchone()
        return model.model_validate_json(row[0]) if row else None

    async def get_version(self, collection: str, doc_id: str) -> int | None:
        table = await self._table(collection)
        db = await self._db()
        async with db.execute(f'SELECT version FROM "{table}" WHERE id = ?', (doc_id,)) as cur:  # noqa: S608
            row = await cur.fetchone()
        return int(row[0]) if row else None

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
        table = await self._table(collection)
        db = await self._db()
        clauses: list[str] = []
        params: list[Any] = []
        for key, value in (where or {}).items():
            path = "$." + check_field(key)
            if isinstance(value, list | tuple | set):
                values = [norm_value(v) for v in value]
                if not values:
                    clauses.append("0")
                    continue
                clauses.append(f"json_extract(data, '{path}') IN ({', '.join('?' * len(values))})")
                params.extend(values)
            else:
                clauses.append(f"json_extract(data, '{path}') = ?")
                params.append(norm_value(value))
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        desc = "DESC" if order_by.startswith("-") else "ASC"
        key = check_field(order_by.lstrip("-+"))
        order_expr = (
            "COALESCE(json_extract(data, '$.created_at'), created_at)"
            if key == "created_at"
            else f"json_extract(data, '$.{key}')"
        )
        async with db.execute(f'SELECT COUNT(*) FROM "{table}" {where_sql}', params) as cur:  # noqa: S608
            total = int((await cur.fetchone() or [0])[0])
        sql = f'SELECT data FROM "{table}" {where_sql} ORDER BY {order_expr} {desc}, id LIMIT ? OFFSET ?'  # noqa: S608
        async with db.execute(sql, [*params, page_size, (max(page, 1) - 1) * page_size]) as cur:
            rows = await cur.fetchall()
        items = [model.model_validate_json(r[0]) for r in rows]
        return Page[model](items=items, pagination=Pagination(page=page, page_size=page_size, total=total))  # type: ignore[valid-type]

    async def delete(self, collection: str, doc_id: str) -> bool:
        table = await self._table(collection)
        db = await self._db()
        cur = await db.execute(f'DELETE FROM "{table}" WHERE id = ?', (doc_id,))  # noqa: S608
        await db.commit()
        return (cur.rowcount or 0) > 0

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            self._tables.clear()
