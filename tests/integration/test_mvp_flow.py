"""MVP integration (plan milestone M2): every *real* module available on main, stubs only where A2/A3
have not delivered yet. Runs over HTTP: upload M001 SAS -> classify -> doc -> rate -> H1 -> rebuild ->
parity -> usability -> H2 -> deploy -> monitoring registration.

Real today: ClassifierAgent (A1), QualityCheckerImpl + MonitoringRegistrarImpl (A4).
Stubs today: DocAgent, DocRater, ReportBuilder (A3), RebuildAgent, ModelRunner (A2).
When a teammate's class lands at its registry path, this test runs it automatically.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mrf.api.app import create_app
from mrf.contracts.models import Dataset, ModelRecord, Schedule
from mrf.orchestrator.registry import Registry
from mrf.storage import Collections, get_repo
from tests.conftest import API_HEADERS as H

SAS = Path(__file__).resolve().parents[1] / "fixtures" / "classify" / "m001_pd_scorecard.sas"


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


def _approve(client: TestClient, review_id: str) -> dict[str, Any]:
    resp = client.post(f"/api/v1/reviews/{review_id}/decision", headers={**H, "X-Operator": "albert"},
                       json={"decision": "approve", "comment": "MVP"})
    assert resp.status_code == 200, resp.text
    return _wait(client, resp.json()["data"]["job_id"])


def test_mvp_m001_end_to_end(client: TestClient) -> None:
    agents = Registry.discover().describe()
    assert agents["classifier"] == "ClassifierAgent"
    assert agents["quality_checker"] == "QualityCheckerImpl" and agents["monitoring"] == "MonitoringRegistrarImpl"

    repo = get_repo()
    ds = Dataset(dataset_id="ds_m001_oot", name="M001 out-of-time", uri="data/clean/german_credit_test.csv",
                 role="out_of_time", schema_name="german_credit_clean")
    asyncio.run(repo.put(Collections.DATASETS, ds.dataset_id, ds))

    resp = client.post("/api/v1/pipelines", headers=H, files=[("files", (SAS.name, SAS.read_bytes()))],
                       data={"model_name": "M001 Retail PD scorecard", "dataset_ids": [ds.dataset_id]})
    assert resp.status_code == 202, resp.text
    started = resp.json()["data"]

    job = _wait(client, started["job_id"])
    assert job["status"] == "succeeded" and job["result"]["gate"] == "H1", job

    model = client.get(f"/api/v1/models/{started['model_id']}", headers=H).json()["data"]
    c = model["classification"]
    assert (c["language"], c["algorithm"], c["purpose"], c["target"]) == (
        "sas", "logistic_regression", "pd", "default_flag",
    )
    assert c["confidence"] >= 0.7 and not c["needs_review"]
    assert c["metadata"]["class_variables"] == {"checking_status": "A14", "credit_history": "A34", "age_band": "3"}

    h2 = _approve(client, job["result"]["review_id"])
    assert h2["result"]["gate"] == "H2"
    done = _approve(client, h2["result"]["review_id"])
    assert done["result"]["state"] == "monitoring"

    pipeline = client.get(f"/api/v1/pipelines/{started['pipeline_id']}", headers=H).json()["data"]
    assert [t["to_state"] for t in pipeline["history"]][-3:] == ["awaiting_signoff", "deployed", "monitoring"]
    assert {"doc_id", "rating_id", "rebuild_id", "run_ids", "validation_report_id"} <= set(pipeline["artifacts"])

    stored = asyncio.run(repo.get(Collections.MODELS, started["model_id"], ModelRecord))
    assert stored.lifecycle == "production"
    assert stored.tags["monitoring.baseline_dataset_id"] == ds.dataset_id  # A4 registrar ran
    assert asyncio.run(repo.get_or_none(Collections.SCHEDULES, started["model_id"], Schedule)) is not None

    # A4 schedule endpoint now accepts the deployed model
    put = client.put(f"/api/v1/monitoring/schedules/{started['model_id']}", headers=H, json={"cron": "0 * * * *"})
    assert put.status_code == 200, put.text
