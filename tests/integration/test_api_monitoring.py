"""A4 monitoring endpoints over HTTP: metrics, alerts, schedules, dataset quality, monitoring runs."""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mrf.api.app import create_app
from mrf.contracts.models import Alert, MonitoringMetric, Schedule
from mrf.storage import Collections, get_repo
from tests.conftest import API_HEADERS as H
from tests.unit.monitoring_helpers import FakeRunner, RevalidationSpy, add_dataset, add_model, frame, install


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(mount_mcp=False)) as c:
        yield c


def wait_job(client: TestClient, job_id: str) -> dict[str, Any]:
    for _ in range(250):
        job: dict[str, Any] = client.get(f"/api/v1/jobs/{job_id}", headers=H).json()["data"]
        if job["status"] in {"succeeded", "failed"}:
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


async def test_metrics_filtered_by_time(client: TestClient) -> None:
    await add_model()
    now = datetime.now(UTC)
    for i, status in enumerate(["green", "amber", "red"]):
        m = MonitoringMetric(model_id="mdl_t", batch_id=f"b{i}", at=now - timedelta(days=2 - i), status=status)
        await get_repo().put(Collections.METRICS, f"mdl_t:b{i}", m)
    items = client.get("/api/v1/monitoring/models/mdl_t/metrics", headers=H).json()["data"]["items"]
    assert [m["status"] for m in items] == ["green", "amber", "red"]
    since = (now - timedelta(hours=36)).isoformat()
    recent = client.get("/api/v1/monitoring/models/mdl_t/metrics", headers=H, params={"from": since}).json()
    assert [m["batch_id"] for m in recent["data"]["items"]] == ["b1", "b2"]
    assert client.get("/api/v1/monitoring/models/nope/metrics", headers=H).json()["code"] == "MRF-1404"


async def test_alerts_filters_and_paging(client: TestClient) -> None:
    for i, sev in enumerate(["amber", "red", "red"]):
        a = Alert(alert_id=f"alr_{i}", model_id="mdl_t", severity=sev, kind="drift", message=f"a{i}")
        await get_repo().put(Collections.ALERTS, a.alert_id, a)
    body = client.get("/api/v1/monitoring/alerts", headers=H, params={"severity": "red", "page_size": 1}).json()
    assert body["data"]["pagination"]["total"] == 2 and len(body["data"]["items"]) == 1
    assert client.get("/api/v1/monitoring/alerts", headers=H, params={"severity": "blue"}).status_code == 422


async def test_put_schedule(client: TestClient) -> None:
    await add_model()
    await add_model("mdl_new", lifecycle="documented")
    resp = client.put("/api/v1/monitoring/schedules/mdl_t", headers=H, json={"cron": "0 * * * *"})
    assert resp.status_code == 200 and resp.json()["data"]["cron"] == "0 * * * *"
    assert (await get_repo().get(Collections.SCHEDULES, "mdl_t", Schedule)).enabled
    not_deployed = client.put("/api/v1/monitoring/schedules/mdl_new", headers=H, json={"cron": "0 * * * *"})
    assert not_deployed.status_code == 409 and not_deployed.json()["code"] == "MRF-3201"
    bad = client.put("/api/v1/monitoring/schedules/mdl_t", headers=H, json={"cron": "hourly"})
    assert bad.status_code == 422


async def test_dataset_quality_endpoint(client: TestClient, tmp_path: Path) -> None:
    await add_dataset(tmp_path, "ds_q", frame(missing=0.1))
    data = client.get("/api/v1/datasets/ds_q/quality", headers=H).json()["data"]
    assert data["passed"] is True and {c["name"] for c in data["checks"]} >= {"row_count", "missing_rate"}
    assert client.get("/api/v1/datasets/ds_none/quality", headers=H).json()["code"] == "MRF-1404"


async def test_monitoring_runs_one_batch_and_tick(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install(monkeypatch, FakeRunner(), RevalidationSpy())
    await add_model()
    await add_dataset(tmp_path, "ds_base", frame(), role="out_of_time")
    await add_dataset(tmp_path, "ds_m1", frame(shift=0.5), role="monitoring_batch", model_id="mdl_t")
    await add_dataset(tmp_path, "ds_m2", frame(), role="monitoring_batch", model_id="mdl_t")
    await get_repo().put(Collections.SCHEDULES, "mdl_t", Schedule(model_id="mdl_t", cron="0 * * * *"))

    one = client.post("/api/v1/monitoring/runs", headers=H, json={"model_id": "mdl_t", "dataset_id": "ds_m1"})
    assert one.status_code == 202
    job = wait_job(client, one.json()["data"]["job_id"])
    assert job["status"] == "succeeded" and job["result"]["status"] == "red"

    tick = client.post("/api/v1/monitoring/runs", headers=H)  # no body: what the Container Apps Job sends
    result = wait_job(client, tick.json()["data"]["job_id"])["result"]
    assert result["processed"] == [{"batch_id": "ds_m2", "status": "green"}]

    bad = client.post("/api/v1/monitoring/runs", headers=H, json={"dataset_id": "ds_m1"})
    assert bad.status_code == 422 and bad.json()["code"] == "MRF-1006"
