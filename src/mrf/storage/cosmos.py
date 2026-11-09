"""Azure Cosmos DB (NoSQL API) document store - cloud backend of :class:`Repository`. Owner: A1.

Layout: one container per collection, partition key ``/id``. Each item:
    {"id": <doc_id>, "doc": <the model as JSON>, "version": n, "created_at": iso, "updated_at": iso}

Auth: managed identity (``DefaultAzureCredential``) in Azure, or ``MRF_COSMOS_KEY`` for the local emulator.
With managed identity the data-plane role cannot create containers, so they must exist (A4's Bicep creates
:data:`REQUIRED_CONTAINERS`). With a key, missing containers are created on first use.

Filters are equality (dotted paths, list = IN); queries are cross-partition, which is fine at our scale
(free tier, < 10k documents). Note: Cosmos ``ORDER BY`` skips documents that lack the sort field.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from mrf.core import MRFCode, MRFError
from mrf.storage.base import Collections, Page, Pagination, T, check_collection, check_field, norm_value, to_doc

REQUIRED_CONTAINERS: list[str] = sorted(
    v for k, v in vars(Collections).items() if not k.startswith("_") and isinstance(v, str)
)


def _path(field: str) -> str:
    """'classification.language' -> c.doc["classification"]["language"] (bracket form avoids reserved words)."""
    return "c.doc" + "".join(f'["{part}"]' for part in check_field(field).split("."))


def build_query(
    where: dict[str, Any] | None, order_by: str, page: int, page_size: int
) -> tuple[str, str, list[dict[str, Any]]]:
    """Returns (select_sql, count_sql, parameters). Pure - unit tested without Cosmos."""
    clauses: list[str] = []
    params: list[dict[str, Any]] = []
    for i, (key, value) in enumerate((where or {}).items()):
        name = f"@p{i}"
        if isinstance(value, list | tuple | set):
            clauses.append(f"ARRAY_CONTAINS({name}, {_path(key)})")
            params.append({"name": name, "value": [norm_value(v) for v in value]})
        else:
            clauses.append(f"{_path(key)} = {name}")
            params.append({"name": name, "value": norm_value(value)})
    where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    desc = "DESC" if order_by.startswith("-") else "ASC"
    key = check_field(order_by.lstrip("-+"))
    order_expr = "c.created_at" if key == "created_at" else _path(key)
    offset = (max(page, 1) - 1) * page_size
    # identifiers are regex-validated (check_field), values are bound parameters
    select = f"SELECT c.doc FROM c{where_sql} ORDER BY {order_expr} {desc} OFFSET {offset} LIMIT {int(page_size)}"  # noqa: S608
    count = f"SELECT VALUE COUNT(1) FROM c{where_sql}"  # noqa: S608
    return select, count, params


class CosmosRepository:
    def __init__(self, endpoint: str, database: str, key: str = "", client: Any | None = None) -> None:
        if not endpoint and client is None:
            raise MRFError(MRFCode.INTERNAL, "MRF_COSMOS_ENDPOINT is not set")
        self.endpoint, self.database, self.key = endpoint, database, key
        self._client = client
        self._db: Any = None
        self._containers: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ connection
    async def _container(self, collection: str) -> Any:
        name = check_collection(collection)
        if name in self._containers:
            return self._containers[name]
        async with self._lock:
            if self._db is None:
                if self._client is None:
                    from azure.cosmos.aio import CosmosClient

                    credential: Any
                    if self.key:
                        credential = self.key
                    else:
                        from azure.identity.aio import DefaultAzureCredential

                        credential = DefaultAzureCredential()
                    self._client = CosmosClient(self.endpoint, credential=credential)
                self._db = self._client.get_database_client(self.database)
            container = self._db.get_container_client(name)
            try:
                await container.read()
            except Exception as exc:
                if not _is_not_found(exc):
                    raise
                if not self.key:
                    raise MRFError(
                        MRFCode.INTERNAL,
                        f"Cosmos container '{name}' does not exist; create it in Bicep (partition key /id)",
                        detail={"required_containers": REQUIRED_CONTAINERS},
                    ) from exc
                from azure.cosmos import PartitionKey

                container = await self._db.create_container_if_not_exists(
                    id=name, partition_key=PartitionKey(path="/id")
                )
            self._containers[name] = container
            return container

    # ------------------------------------------------------------------ Repository API
    async def _read(self, container: Any, doc_id: str) -> dict[str, Any] | None:
        try:
            item: dict[str, Any] = await container.read_item(item=doc_id, partition_key=doc_id)
            return item
        except Exception as exc:
            if _is_not_found(exc):
                return None
            raise

    async def put(
        self, collection: str, doc_id: str, doc: BaseModel | dict[str, Any], *, if_version: int | None = None
    ) -> int:
        container = await self._container(collection)
        current = await self._read(container, doc_id)
        cur_version = int(current["version"]) if current else 0
        if if_version is not None and if_version != cur_version:
            raise MRFError(
                MRFCode.INVALID_STATE,
                f"{collection}/{doc_id} was modified concurrently",
                detail={"expected_version": if_version, "actual_version": cur_version},
            )
        now = datetime.now(UTC).isoformat()
        body = {
            "id": doc_id,
            "doc": to_doc(doc),
            "version": cur_version + 1,
            "created_at": current["created_at"] if current else now,
            "updated_at": now,
        }
        try:
            if current is None:
                await container.create_item(body=body)
            else:
                from azure.core import MatchConditions

                await container.replace_item(
                    item=doc_id, body=body, etag=current.get("_etag"), match_condition=MatchConditions.IfNotModified
                )
        except Exception as exc:
            if _status(exc) in {409, 412}:  # created / changed by someone else in between
                raise MRFError(MRFCode.INVALID_STATE, f"{collection}/{doc_id} was modified concurrently") from exc
            raise
        return cur_version + 1

    async def get(self, collection: str, doc_id: str, model: type[T]) -> T:
        found = await self.get_or_none(collection, doc_id, model)
        if found is None:
            raise MRFError(MRFCode.NOT_FOUND, f"{collection}/{doc_id} not found")
        return found

    async def get_or_none(self, collection: str, doc_id: str, model: type[T]) -> T | None:
        item = await self._read(await self._container(collection), doc_id)
        return model.model_validate(item["doc"]) if item else None

    async def get_version(self, collection: str, doc_id: str) -> int | None:
        item = await self._read(await self._container(collection), doc_id)
        return int(item["version"]) if item else None

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
        container = await self._container(collection)
        select, count, params = build_query(where, order_by, page, page_size)
        total = 0
        async for value in container.query_items(query=count, parameters=params):
            total = int(value)
        items = [
            model.model_validate(row["doc"]) async for row in container.query_items(query=select, parameters=params)
        ]
        return Page[model](items=items, pagination=Pagination(page=page, page_size=page_size, total=total))  # type: ignore[valid-type]

    async def delete(self, collection: str, doc_id: str) -> bool:
        container = await self._container(collection)
        try:
            await container.delete_item(item=doc_id, partition_key=doc_id)
            return True
        except Exception as exc:
            if _is_not_found(exc):
                return False
            raise

    async def close(self) -> None:
        if self._client is not None and hasattr(self._client, "close"):
            await self._client.close()
        self._client, self._db, self._containers = None, None, {}


def _status(exc: Exception) -> int | None:
    return getattr(exc, "status_code", None)


def _is_not_found(exc: Exception) -> bool:
    return _status(exc) == 404
