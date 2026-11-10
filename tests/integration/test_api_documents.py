"""Documents API: regenerate (draft + rate loop) as a job, list, fetch as json / markdown / html, ratings."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mrf.api.app import create_app
from mrf.llm import get_mock
from tests.conftest import API_HEADERS as H
from tests.unit.a3_helpers import m001_context


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def _wait(client: TestClient, job_id: str) -> dict[str, Any]:
    for _ in range(300):
        job: dict[str, Any] = client.get(f"/api/v1/jobs/{job_id}", headers=H).json()["data"]
        if job["status"] in {"succeeded", "failed"}:
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_regenerate_list_get_and_ratings(client: TestClient) -> None:
    ctx = asyncio.run(m001_context())
    mid = ctx.model.model_id
    resp = client.post(f"/api/v1/models/{mid}/documents", headers=H, json={"feedback": ["mention the age bands"]})
    assert resp.status_code == 202, resp.text
    job = _wait(client, resp.json()["data"]["job_id"])
    assert job["status"] == "succeeded", job
    result = job["result"]
    assert result["passed"] is True and result["attempts"] == 1 and result["total"] >= 80

    listing = client.get(f"/api/v1/models/{mid}/documents", headers=H).json()["data"]
    assert [d["doc_id"] for d in listing["items"]] == [result["doc_id"]] and listing["pagination"]["total"] == 1

    doc = client.get(f"/api/v1/models/{mid}/documents/{result['doc_id']}", headers=H).json()["data"]
    assert doc["status"] == "rated" and set(doc["sections"]) >= {"data", "methodology", "governance"}
    assert doc["evidence"][0]["ref"].startswith("tool:parse_code#call_")

    md = client.get(f"/api/v1/models/{mid}/documents/{result['doc_id']}?format=markdown", headers=H)
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert md.text.startswith("# Model Documentation")
    page = client.get(f"/api/v1/models/{mid}/documents/{result['doc_id']}?format=html", headers=H)
    assert page.headers["content-type"].startswith("text/html")
    assert "<table>" in page.text and "<code>checking_status</code>" in page.text

    ratings = client.get(f"/api/v1/models/{mid}/documents/{result['doc_id']}/ratings", headers=H).json()["data"]
    assert [r["rating_id"] for r in ratings["items"]] == [result["rating_id"]]
    writer_prompt = next(c for c in get_mock().calls if c.role == "doc_writer").messages[-1].content
    assert "mention the age bands" in writer_prompt


def test_failed_rating_redrafts_with_comments(client: TestClient) -> None:
    ctx = asyncio.run(m001_context())
    low = {"methodology_accuracy": 0, "limitations_adequacy": 0, "clarity": 0, "comments": ["Add more detail."]}
    get_mock().register("rater", [low, low, {"methodology_accuracy": 14, "limitations_adequacy": 13, "clarity": 9}])
    resp = client.post(f"/api/v1/models/{ctx.model.model_id}/documents", headers=H, json={})
    job = _wait(client, resp.json()["data"]["job_id"])
    assert job["result"]["attempts"] == 3 and job["result"]["passed"] is True
    prompts = [c.messages[-1].content for c in get_mock().calls if c.role == "doc_writer"]
    assert len(prompts) == 3 and "Add more detail." in prompts[1]


def test_no_rate_and_errors(client: TestClient) -> None:
    ctx = asyncio.run(m001_context())
    mid = ctx.model.model_id
    job = _wait(
        client, client.post(f"/api/v1/models/{mid}/documents", headers=H, json={"rate": False}).json()["data"]["job_id"]
    )
    assert job["result"]["passed"] is None and "rating_id" not in job["result"]
    assert client.post("/api/v1/models/mdl_nope/documents", headers=H, json={}).status_code == 404
    other = client.get(f"/api/v1/models/mdl_other/documents/{job['result']['doc_id']}", headers=H)
    assert other.status_code == 404 and other.json()["errors"][0]["code"] == "MRF-1404"
    assert client.get(f"/api/v1/models/{mid}/documents/doc_x?format=pdf", headers=H).status_code == 422
