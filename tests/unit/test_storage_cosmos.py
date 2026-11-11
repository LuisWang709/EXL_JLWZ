"""CosmosRepository against a fake container that interprets the SQL subset build_query generates.

Real-Cosmos verification happens on the dev deployment (A4); this pins semantics + query shape.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import AsyncIterator
from typing import Any

import pytest

from mrf.contracts.models import Pipeline, Review
from mrf.core import MRFCode, MRFError
from mrf.storage.cosmos import REQUIRED_CONTAINERS, CosmosRepository, build_query


class FakeHttpError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(status_code)
        self.status_code = status_code


def _get(doc: dict[str, Any], path: str) -> Any:
    cur: Any = doc
    for part in re.findall(r'\["([^"]+)"\]', path):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


class FakeContainer:
    _etags = itertools.count(1)

    def __init__(self, exists: bool = True) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.exists = exists
        self.queries: list[str] = []

    async def read(self) -> dict[str, Any]:
        if not self.exists:
            raise FakeHttpError(404)
        return {}

    async def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        if item not in self.items:
            raise FakeHttpError(404)
        return dict(self.items[item])

    async def create_item(self, body: dict[str, Any]) -> None:
        if body["id"] in self.items:
            raise FakeHttpError(409)
        self.items[body["id"]] = {**body, "_etag": str(next(self._etags))}

    async def replace_item(self, item: str, body: dict[str, Any], etag: str, match_condition: Any) -> None:
        if self.items[item]["_etag"] != etag:
            raise FakeHttpError(412)
        self.items[item] = {**body, "_etag": str(next(self._etags))}

    async def delete_item(self, item: str, partition_key: str) -> None:
        if self.items.pop(item, None) is None:
            raise FakeHttpError(404)

    async def query_items(self, query: str, parameters: list[dict[str, Any]]) -> AsyncIterator[Any]:
        self.queries.append(query)
        values = {p["name"]: p["value"] for p in parameters}
        rows = list(self.items.values())
        for path, name in re.findall(r'(c\.doc(?:\["[^"]+"\])+) = (@p\d+)', query):
            rows = [r for r in rows if _get(r["doc"], path) == values[name]]
        for name, path in re.findall(r"ARRAY_CONTAINS\((@p\d+), (c\.doc(?:\[\"[^\"]+\"\])+)\)", query):
            rows = [r for r in rows if _get(r["doc"], path) in values[name]]
        if query.startswith("SELECT VALUE COUNT(1)"):
            yield len(rows)
            return
        m = re.search(r"ORDER BY (\S+) (ASC|DESC) OFFSET (\d+) LIMIT (\d+)", query)
        assert m, query
        key = (lambda r: r["created_at"]) if m.group(1) == "c.created_at" else (lambda r: _get(r["doc"], m.group(1)))
        rows.sort(key=key, reverse=m.group(2) == "DESC")
        for r in rows[int(m.group(3)) : int(m.group(3)) + int(m.group(4))]:
            yield {"doc": r["doc"]}


class FakeDatabase:
    def __init__(self, exists: bool = True) -> None:
        self.containers: dict[str, FakeContainer] = {}
        self.exists = exists
        self.created: list[str] = []

    def get_container_client(self, name: str) -> FakeContainer:
        return self.containers.setdefault(name, FakeContainer(self.exists))

    async def create_container_if_not_exists(self, id: str, partition_key: Any) -> FakeContainer:
        self.created.append(id)
        c = self.containers[id]
        c.exists = True
        return c


class FakeClient:
    def __init__(self, exists: bool = True) -> None:
        self.db = FakeDatabase(exists)

    def get_database_client(self, name: str) -> FakeDatabase:
        return self.db

    async def close(self) -> None:
        return None


def test_build_query_shape() -> None:
    select, count, params = build_query(
        {"status": "pending", "gate": ["H1", "H2"], "payload.n": 3}, "-created_at", 2, 10
    )
    assert select == (
        'SELECT c.doc FROM c WHERE c.doc["status"] = @p0 AND ARRAY_CONTAINS(@p1, c.doc["gate"]) AND '
        'c.doc["payload"]["n"] = @p2 ORDER BY c.created_at DESC OFFSET 10 LIMIT 10'
    )
    assert count.startswith("SELECT VALUE COUNT(1) FROM c WHERE")
    assert params[1] == {"name": "@p1", "value": ["H1", "H2"]}
    with pytest.raises(ValueError):
        build_query({'a"] OR 1=1 --': 1}, "-created_at", 1, 10)


async def test_crud_versions_and_conflicts() -> None:
    repo = CosmosRepository("https://x", "mrf", client=FakeClient())
    p = Pipeline(pipeline_id="pl_1", model_id="m")
    assert await repo.put("pipelines", "pl_1", p) == 1
    assert await repo.put("pipelines", "pl_1", p, if_version=1) == 2
    with pytest.raises(MRFError) as e:
        await repo.put("pipelines", "pl_1", p, if_version=1)
    assert e.value.code is MRFCode.INVALID_STATE
    assert (await repo.get("pipelines", "pl_1", Pipeline)).model_id == "m"
    assert await repo.get_version("pipelines", "pl_1") == 2
    with pytest.raises(MRFError) as e:
        await repo.get("pipelines", "nope", Pipeline)
    assert e.value.code is MRFCode.NOT_FOUND
    assert await repo.delete("pipelines", "pl_1") and not await repo.delete("pipelines", "pl_1")


async def test_concurrent_replace_maps_412_to_invalid_state() -> None:
    client = FakeClient()
    repo = CosmosRepository("https://x", "mrf", client=client)
    await repo.put("reviews", "r1", {"x": 1})
    container = client.db.containers["reviews"]
    real_read = container.read_item

    async def stale_read(item: str, partition_key: str) -> dict[str, Any]:
        doc = await real_read(item, partition_key)
        container.items[item]["_etag"] = "changed-by-someone-else"
        return doc

    container.read_item = stale_read  # type: ignore[method-assign]
    with pytest.raises(MRFError) as e:
        await repo.put("reviews", "r1", {"x": 2})
    assert e.value.code is MRFCode.INVALID_STATE


async def test_find_filters_and_paging() -> None:
    repo = CosmosRepository("https://x", "mrf", client=FakeClient())
    for i in range(5):
        r = Review(
            review_id=f"rev_{i}",
            pipeline_id="pl",
            model_id="m",
            gate="H1" if i % 2 else "H2",
            reason="x",
            status="pending" if i < 3 else "approved",
            payload={"n": i},
        )
        await repo.put("reviews", r.review_id, r)
    page = await repo.find("reviews", Review, where={"status": "pending"}, page_size=2, order_by="review_id")
    assert page.pagination.total == 3 and [r.review_id for r in page.items] == ["rev_0", "rev_1"]
    page = await repo.find("reviews", Review, where={"gate": ["H1"], "payload.n": 3})
    assert [r.review_id for r in page.items] == ["rev_3"]


async def test_missing_container_with_managed_identity_explains_and_with_key_creates() -> None:
    repo = CosmosRepository("https://x", "mrf", client=FakeClient(exists=False))
    with pytest.raises(MRFError) as e:
        await repo.get_or_none("jobs", "j", Pipeline)
    assert "create it in Bicep" in e.value.message and e.value.detail["required_containers"] == REQUIRED_CONTAINERS
    client = FakeClient(exists=False)
    keyed = CosmosRepository("https://localhost:8081", "mrf", key="emulator-key", client=client)
    assert await keyed.get_or_none("jobs", "j", Pipeline) is None and client.db.created == ["jobs"]


def test_required_containers_cover_all_collections() -> None:
    assert {"pipelines", "jobs", "reviews", "audit", "idempotency", "monitoring_metrics"} <= set(REQUIRED_CONTAINERS)


def test_bicep_containers_match_collections() -> None:
    """With managed identity the app cannot create containers, so infra/modules/cosmos-db.bicep must list
    exactly mrf.storage.Collections (issue #17). Adding a collection without the Bicep line fails here."""
    from mrf.config import REPO_ROOT

    bicep = (REPO_ROOT / "infra" / "modules" / "cosmos-db.bicep").read_text(encoding="utf-8")
    block = re.search(r"var containers = \[(.*?)\]", bicep, re.DOTALL)
    assert block, "containers list not found in cosmos-db.bicep"
    assert sorted(re.findall(r"'([a-z_]+)'", block.group(1))) == REQUIRED_CONTAINERS
