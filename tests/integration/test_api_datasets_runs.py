"""Datasets, rebuilds and runs over HTTP (A2's endpoints)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from mrf.api.app import create_app
from tests.conftest import API_HEADERS as H

ROOT = Path(__file__).resolve().parents[2]
SAS = ROOT / "models" / "legacy" / "M001_sas_pd_scorecard" / "m001_pd_scorecard.sas"
SAMPLE = ROOT / "tests" / "fixtures" / "m001" / "input_sample.csv"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def _wait(client: TestClient, job_id: str) -> dict[str, Any]:
    for _ in range(600):
        job: dict[str, Any] = client.get(f"/api/v1/jobs/{job_id}", headers=H).json()["data"]
        if job["status"] in {"succeeded", "failed"}:
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def _csv() -> bytes:
    return pd.read_csv(SAMPLE).astype({"credit_amount": float}).to_csv(index=False).encode()


def _upload(client: TestClient, filename: str = "oot.csv", data: bytes | None = None, **form: str) -> Any:
    return client.post("/api/v1/datasets", headers=H, files=[("file", (filename, data or _csv()))], data=form)


def test_upload_registers_and_describes_the_dataset(client: TestClient) -> None:
    resp = _upload(client, role="out_of_time", schema_name="german_credit_clean", name="M001 hold-out")
    assert resp.status_code == 201, resp.text
    ds = resp.json()["data"]
    assert ds["row_count"] == 300 and ds["format"] == "csv" and ds["role"] == "out_of_time"
    roles = {c["name"]: c["role"] for c in ds["columns"]}
    assert roles["id"] == "id" and roles["default_flag"] == "target" and roles["log_amount"] == "feature"

    got = client.get(f"/api/v1/datasets/{ds['dataset_id']}", headers=H).json()["data"]
    assert got["name"] == "M001 hold-out"
    listed = client.get("/api/v1/datasets?role=out_of_time", headers=H).json()["data"]
    assert listed["pagination"]["total"] == 1
    quality = client.get(f"/api/v1/datasets/{ds['dataset_id']}/quality", headers=H).json()["data"]
    assert quality["passed"] is True

    # a JSON reference to the stored file works; a path outside the blob store does not
    again = client.post("/api/v1/datasets", headers=H, json={"name": "same file", "uri": ds["uri"]})
    assert again.status_code == 201 and again.json()["data"]["row_count"] == 300
    outside = client.post("/api/v1/datasets", headers=H, json={"name": "x", "uri": "file:///etc/passwd"})
    assert outside.status_code == 422 and outside.json()["code"] == "MRF-1006"


def test_upload_rejections(client: TestClient) -> None:
    assert _upload(client, "model.exe", b"MZ").json()["code"] == "MRF-1001"
    assert _upload(client, "broken.parquet", b"not parquet").json()["code"] == "MRF-1003"
    pii = _upload(client, "people.csv", b"id,email\n1,jane.doe@bank.example\n")
    assert pii.status_code == 422 and pii.json()["code"] == "MRF-1004" and "jane" not in pii.text
    assert _upload(client, schema_name="nope").json()["code"] == "MRF-1006"
    assert _upload(client, model_id="mdl_missing").json()["code"] == "MRF-1404"
    assert client.get("/api/v1/datasets/ds_missing", headers=H).json()["code"] == "MRF-1404"


def test_pipeline_with_uploaded_datasets_then_standalone_rebuild_and_run(client: TestClient) -> None:
    frame = pd.read_csv(SAMPLE).astype({"credit_amount": float})
    ids = []
    for name, part, role in (
        ("dev.csv", frame.iloc[:150], "development"),
        ("oot.csv", frame.iloc[150:], "out_of_time"),
    ):
        resp = _upload(client, name, part.to_csv(index=False).encode(), role=role, schema_name="german_credit_clean")
        ids.append(resp.json()["data"]["dataset_id"])

    started = client.post(
        "/api/v1/pipelines",
        headers=H,
        files=[("files", (SAS.name, SAS.read_bytes()))],
        data={"model_name": "M001 Retail PD scorecard", "dataset_ids": ids, "options": '{"auto_approve": true}'},
    ).json()["data"]
    job = _wait(client, started["job_id"])
    assert job["status"] == "succeeded" and job["result"]["state"] == "monitoring", job
    mid = started["model_id"]

    runs = client.get(f"/api/v1/models/{mid}/runs", headers=H).json()["data"]["items"]
    assert len(runs) == 2 and all(r["status"] == "succeeded" and "gini" in r["metrics"] for r in runs)
    oot_run = next(r for r in runs if r["dataset_id"] == ids[1])
    assert oot_run["metrics"]["psi_reference"] == f"dataset:{ids[0]}"
    rebuilds = client.get(f"/api/v1/models/{mid}/rebuilds", headers=H).json()["data"]["items"]
    assert len(rebuilds) == 1 and rebuilds[0]["status"] == "passed"

    # standalone rebuild and run (outside the pipeline)
    resp = client.post(f"/api/v1/models/{mid}/rebuilds", headers=H, json={"max_attempts": 2})
    assert resp.status_code == 202, resp.text
    result = _wait(client, resp.json()["data"]["job_id"])["result"]
    assert result["passed"] is True and result["attempts"] == 1
    resp = client.post(
        f"/api/v1/models/{mid}/runs", headers=H, json={"dataset_id": ids[1], "reference_dataset_id": ids[0]}
    )
    assert resp.status_code == 202, resp.text
    run_id = _wait(client, resp.json()["data"]["job_id"])["result"]["run_id"]
    run = client.get(f"/api/v1/models/{mid}/runs/{run_id}", headers=H).json()["data"]
    assert run["metrics"]["n_records"] == 150 and run["outputs"][0]["filename"] == "scores.csv"

    assert client.post(f"/api/v1/models/{mid}/runs", headers=H, json={"dataset_id": "ds_nope"}).status_code == 404
    assert client.get(f"/api/v1/models/{mid}/rebuilds/rb_nope", headers=H).status_code == 404
