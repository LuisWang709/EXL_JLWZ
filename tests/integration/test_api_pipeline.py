"""API end to end with stub agents: upload -> H1 -> H2 -> monitoring, via HTTP only."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mrf.api.app import create_app
from tests.conftest import API_HEADERS as H

SAS = b"proc logistic data=d; model y(event='1') = x1 x2; run;"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def _wait_job(client: TestClient, job_id: str) -> dict[str, Any]:
    for _ in range(250):
        job: dict[str, Any] = client.get(f"/api/v1/jobs/{job_id}", headers=H).json()["data"]
        if job["status"] in {"succeeded", "failed"}:
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def _start(client: TestClient, key: str | None = None) -> dict[str, Any]:
    headers = {**H, **({"Idempotency-Key": key} if key else {})}
    resp = client.post(
        "/api/v1/pipelines",
        headers=headers,
        files=[("files", ("m001.sas", SAS))],
        data={"model_name": "M001 PD", "dataset_ids": ["ds_dev"]},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "accepted" and body["code"] == "MRF-0202"
    data: dict[str, Any] = body["data"]
    return data


def _decide(client: TestClient, review_id: str, decision: str = "approve") -> dict[str, Any]:
    resp = client.post(
        f"/api/v1/reviews/{review_id}/decision", headers={**H, "X-Operator": "albert"}, json={"decision": decision}
    )
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


def test_full_flow_over_http(client: TestClient) -> None:
    data = _start(client)
    job = _wait_job(client, data["job_id"])
    assert job["status"] == "succeeded" and job["result"]["gate"] == "H1"

    pending = client.get("/api/v1/reviews?status=pending&gate=H1", headers=H).json()["data"]
    assert pending["pagination"]["total"] == 1
    review_id = pending["items"][0]["review_id"]
    assert _wait_job(client, _decide(client, review_id)["job_id"])["result"]["gate"] == "H2"

    again = client.post(
        f"/api/v1/reviews/{review_id}/decision", headers={**H, "X-Operator": "x"}, json={"decision": "approve"}
    )
    assert again.status_code == 409 and again.json()["code"] == "MRF-3201"

    h2 = client.get("/api/v1/reviews?status=pending&gate=H2", headers=H).json()["data"]["items"][0]
    bad = client.post(
        f"/api/v1/reviews/{h2['review_id']}/decision", headers={**H, "X-Operator": "x"}, json={"decision": "edit"}
    )
    assert bad.status_code == 422
    assert _wait_job(client, _decide(client, h2["review_id"])["job_id"])["result"]["state"] == "monitoring"

    p = client.get(f"/api/v1/pipelines/{data['pipeline_id']}", headers=H).json()["data"]
    assert p["state"] == "monitoring" and p["history"][0]["to_state"] == "received"
    m = client.get(f"/api/v1/models/{data['model_id']}", headers=H).json()["data"]
    assert m["lifecycle"] == "production" and m["classification"]["language"] == "sas"
    assert client.get("/api/v1/models?language=sas", headers=H).json()["data"]["pagination"]["total"] == 1


def test_idempotent_upload(client: TestClient) -> None:
    a, b = _start(client, key="up-1"), _start(client, key="up-1")
    assert a["job_id"] == b["job_id"] and a["pipeline_id"] == b["pipeline_id"]
    assert client.get("/api/v1/pipelines", headers=H).json()["data"]["pagination"]["total"] == 1


def test_auth_and_errors(client: TestClient) -> None:
    assert client.get("/api/v1/pipelines").status_code == 401
    nf = client.get("/api/v1/pipelines/pl_nope", headers=H)
    assert nf.status_code == 404 and nf.json()["code"] == "MRF-1404" and nf.json()["errors"]
    bad_type = client.post(
        "/api/v1/pipelines", headers=H, files=[("files", ("x.exe", b"MZ"))], data={"model_name": "x"}
    )
    assert bad_type.status_code == 415 and bad_type.json()["code"] == "MRF-1001"
    assert client.get("/nope").json()["code"] == "MRF-1404"


def test_health_and_request_id(client: TestClient) -> None:
    resp = client.get("/healthz", headers={"X-Request-ID": "abc"})
    assert resp.json()["request_id"] == "abc" and resp.headers["X-Request-ID"] == "abc"
    assert client.get("/readyz").json()["data"]["ready"] is True


def test_mcp_mounted(client: TestClient) -> None:
    resp = client.post(
        "/mcp/",
        headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert resp.status_code != 404
