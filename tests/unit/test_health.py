"""/healthz and /readyz (A4)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from mrf.api.app import create_app
from mrf.config import get_settings


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(mount_mcp=False, start_workers=False)) as c:
        yield c


def test_healthz_is_alive(client: TestClient) -> None:
    body = client.get("/healthz").json()
    assert body["status"] == "success" and body["data"]["alive"] is True


def test_readyz_ok_with_mock_llm(client: TestClient) -> None:
    resp = client.get("/readyz")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["ready"] is True and data["checks"] == {"storage": "ok", "data_dir": "ok", "llm_config": "ok"}


def test_readyz_503_when_llm_endpoint_missing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MRF_LLM_PROVIDER", "azure_openai")
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    get_settings.cache_clear()
    resp = client.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "error" and body["code"] == "MRF-5000"
    assert body["data"]["ready"] is False
    assert body["data"]["checks"]["llm_config"] == "missing AZURE_OPENAI_ENDPOINT"


def test_readyz_503_when_storage_fails(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from mrf import storage

    class Broken(storage.MemoryRepository):
        async def find(self, *args, **kwargs):  # type: ignore[no-untyped-def, override]
            raise RuntimeError("db down")

    storage.set_repo(Broken())
    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["data"]["checks"]["storage"] == "error: RuntimeError"


def test_readyz_reports_runtime_without_secrets(client: TestClient) -> None:
    data = client.get("/readyz").json()["data"]
    assert data["runtime"] == {
        "env": "local",
        "storage_backend": "memory",
        "llm_provider": "mock",
        "llm_model": data["runtime"]["llm_model"],
        "guards_enabled": True,
    }
    assert "test-key" not in str(data)
