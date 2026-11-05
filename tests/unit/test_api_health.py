from __future__ import annotations

from fastapi.testclient import TestClient

from mrf.api.app import create_app


def test_healthz_uses_envelope_and_request_id() -> None:
    client = TestClient(create_app())
    resp = client.get("/healthz", headers={"X-Request-ID": "abc"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success" and body["request_id"] == "abc"
    assert resp.headers["X-Request-ID"] == "abc"


def test_readyz() -> None:
    resp = TestClient(create_app()).get("/readyz")
    assert resp.status_code == 200 and resp.json()["data"]["ready"] is True
