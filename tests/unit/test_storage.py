from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from mrf.contracts.models import Pipeline, Review
from mrf.core import MRFCode, MRFError, PipelineState
from mrf.storage import LocalBlobStore, MemoryRepository, Repository, SqliteRepository


@pytest.fixture(params=["memory", "sqlite"])
async def repo(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Repository]:
    r: Repository = MemoryRepository() if request.param == "memory" else SqliteRepository(tmp_path / "t.sqlite")
    yield r
    await r.close()


async def test_put_get_version_and_conflict(repo: Repository) -> None:
    p = Pipeline(pipeline_id="pl_1", model_id="m1")
    assert await repo.put("pipelines", "pl_1", p) == 1
    assert (await repo.get("pipelines", "pl_1", Pipeline)).state is PipelineState.RECEIVED
    assert await repo.put("pipelines", "pl_1", p, if_version=1) == 2
    with pytest.raises(MRFError) as e:
        await repo.put("pipelines", "pl_1", p, if_version=1)
    assert e.value.code is MRFCode.INVALID_STATE
    with pytest.raises(MRFError) as e:
        await repo.get("pipelines", "nope", Pipeline)
    assert e.value.code is MRFCode.NOT_FOUND


async def test_find_filters_nested_in_and_paging(repo: Repository) -> None:
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
    assert await repo.delete("reviews", "rev_3") and not await repo.delete("reviews", "rev_3")


async def test_rejects_bad_names(repo: Repository) -> None:
    with pytest.raises(ValueError):
        await repo.find('x"; drop', Review)
    with pytest.raises(ValueError):
        await repo.find("reviews", Review, where={"a') OR 1=1 --": 1})


async def test_local_blobs_roundtrip_and_traversal(tmp_path: Path) -> None:
    blobs = LocalBlobStore(tmp_path / "store")
    ref = await blobs.put_bytes("models/m1/source/a.sas", b"proc logistic;", media_type="text/plain")
    assert ref.size_bytes == 14 and ref.sha256 and await blobs.get_bytes(ref.uri) == b"proc logistic;"
    assert await blobs.get_bytes("models/m1/source/a.sas") == b"proc logistic;"
    with pytest.raises(MRFError):
        await blobs.put_bytes("../escape.txt", b"x")
    assert not await blobs.exists((tmp_path / "other.txt").as_uri())
