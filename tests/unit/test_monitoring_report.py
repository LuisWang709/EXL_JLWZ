"""A4 monitoring report: cron matcher, report content and number check, scheduling, A3 delegation, API."""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mrf.api.app import create_app
from mrf.contracts.agents import StepContext
from mrf.contracts.models import Alert, ModelRecord, MonitoringMetric, Report, Run, Schedule
from mrf.monitoring.batch import process_pending, report_due
from mrf.monitoring.cron import Cron, fired_between
from mrf.monitoring.registrar import TAG_BASELINE_DATASET, TAG_BASELINE_RUN
from mrf.monitoring.report import MonitoringReportBuilder, generate
from mrf.reporting.builder import ReportBuilderImpl
from mrf.storage import Collections, get_blobs, get_repo
from tests.conftest import API_HEADERS as H
from tests.unit.monitoring_helpers import FakeRunner, RevalidationSpy, add_dataset, frame, install

MONDAY_6 = datetime(2026, 11, 9, 6, 0, tzinfo=UTC)  # a Monday


# ---------------------------------------------------------------------------------------------- cron
def test_cron_weekly_and_steps() -> None:
    weekly = Cron("0 6 * * 1")
    assert weekly.matches(MONDAY_6)
    assert not weekly.matches(MONDAY_6 + timedelta(minutes=1))
    assert not weekly.matches(MONDAY_6 + timedelta(days=1))
    every_15 = Cron("*/15 * * * *")
    assert every_15.matches(MONDAY_6 + timedelta(minutes=45)) and not every_15.matches(MONDAY_6 + timedelta(minutes=5))
    assert Cron("0 6 * * 7").matches(MONDAY_6 - timedelta(days=1))  # 7 = Sunday


def test_cron_day_of_month_or_day_of_week() -> None:
    either = Cron("0 6 1 * 1")  # the 1st of the month OR a Monday, as in classic cron
    assert either.matches(MONDAY_6)
    assert either.matches(datetime(2026, 12, 1, 6, 0, tzinfo=UTC))  # a Tuesday


def test_fired_between() -> None:
    assert fired_between("0 6 * * 1", MONDAY_6 - timedelta(hours=1), MONDAY_6)
    assert not fired_between("0 6 * * 1", MONDAY_6, MONDAY_6 + timedelta(days=6))
    with pytest.raises(ValueError):
        Cron("0 25 * * *")
    with pytest.raises(ValueError):
        Cron("* * *")


# ---------------------------------------------------------------------------------------------- report
async def seed(model_id: str = "mdl_r", with_batches: bool = True) -> ModelRecord:
    repo = get_repo()
    baseline = Run(
        run_id="run_base",
        model_id=model_id,
        dataset_id="ds_base",
        kind="usability",
        status="succeeded",
        metrics={"gini": 0.52},
    )
    await repo.put(Collections.RUNS, baseline.run_id, baseline)
    model = ModelRecord(
        model_id=model_id,
        name="M001 PD scorecard",
        lifecycle="production",
        tags={TAG_BASELINE_DATASET: "ds_base", TAG_BASELINE_RUN: "run_base"},
    )
    await repo.put(Collections.MODELS, model_id, model)
    await repo.put(Collections.SCHEDULES, model_id, Schedule(model_id=model_id, cron="0 6 * * 1"))
    if with_batches:
        now = datetime.now(UTC)
        rows = [
            ("month_01_normal", "green", {"__score__": 0.03, "A11": 0.02, "age": 0.04}, 0.51, {"age": 0.0}),
            ("month_02_young", "amber", {"__score__": 0.12, "A11": 0.05, "age": 0.18}, 0.50, {"age": 0.01}),
            ("month_03_downturn", "red", {"__score__": 0.31, "A11": 0.42, "age": 0.09}, 0.44, {"age": 0.02}),
        ]
        for i, (batch, status, psi, gini, missing) in enumerate(rows):
            metric = MonitoringMetric(
                model_id=model_id,
                batch_id=batch,
                at=now - timedelta(days=3 - i),
                row_count=1000 + i,
                psi=psi,
                gini=gini,
                missing_rate=missing,
                status=status,
            )
            await repo.put(Collections.METRICS, f"{model_id}:{batch}", metric)
        alert = Alert(
            alert_id="alr_1",
            model_id=model_id,
            severity="red",
            kind="drift",
            message="PSI 0.420 on A11 > 0.25",
        )
        await repo.put(Collections.ALERTS, alert.alert_id, alert)
    return model


async def html_of(report: Report) -> str:
    assert report.artifact is not None
    return (await get_blobs().get_bytes(report.artifact.uri)).decode("utf-8")


async def test_report_content_and_number_check() -> None:
    model = await seed()
    report = await MonitoringReportBuilder().build(StepContext(pipeline_id="", model=model))

    assert report.type == "monitoring" and report.rag_status == "red"
    assert report.summary["number_check"]["passed"] and report.summary["batches"] == 3
    assert report.summary["latest_batch"] == "month_03_downturn"
    metrics = report.summary["metrics"]
    assert metrics["batch.2.psi_score"] == 0.31 and metrics["batch.2.max_feature_psi"] == 0.42
    assert metrics["summary.red"] == 1 and metrics["baseline.gini"] == 0.52
    assert metrics["latest.gini_drop"] == pytest.approx(0.08)
    page = await html_of(report)
    assert "Monitoring report" in page and "month_03_downturn" in page and "<svg" in page
    assert "PSI 0.420 on A11" in page  # the alert message is quoted as recorded
    assert page.index("latest.feature.A11.psi") < page.index("latest.feature.age.psi")  # most drifted first


async def test_report_without_batches() -> None:
    model = await seed(with_batches=False)
    report = await MonitoringReportBuilder().build(StepContext(pipeline_id="", model=model))
    assert report.rag_status is None and report.summary["batches"] == 0
    assert "No monitoring batch" in report.summary["findings"][0]


async def test_untraceable_number_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from mrf.core import MRFError
    from mrf.monitoring import report as module

    model = await seed()
    original = module.render
    monkeypatch.setattr(module, "render", lambda *a: original(*a).replace("</body>", "<p>saved 42 hours</p></body>"))
    with pytest.raises(MRFError, match="number check"):
        await MonitoringReportBuilder().build(StepContext(pipeline_id="", model=model))


async def test_a3_report_builder_delegates() -> None:
    model = await seed()
    report = await ReportBuilderImpl().build(StepContext(pipeline_id="", model=model), "monitoring")
    assert report.type == "monitoring" and report.rag_status == "red"


# ---------------------------------------------------------------------------------------------- scheduling
async def monitoring_reports(model_id: str) -> list[Report]:
    page = await get_repo().find(Collections.REPORTS, Report, where={"model_id": model_id, "type": "monitoring"})
    return page.items


async def test_report_after_new_batches_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeRunner(), RevalidationSpy())
    await seed("mdl_t", with_batches=False)
    await add_dataset(tmp_path, "ds_base", frame(), role="out_of_time")
    await add_dataset(tmp_path, "ds_m1", frame(shift=0.4), role="monitoring_batch", model_id="mdl_t")

    first = await process_pending()
    assert [r["status"] for r in first["reports"]] == ["red"]
    second = await process_pending()  # nothing new, weekly cron not due
    assert second["reports"] == [] and len(await monitoring_reports("mdl_t")) == 1


async def test_report_due_by_cron() -> None:
    sched = Schedule(model_id="mdl_c", cron="0 6 * * 1")
    assert await report_due(sched, new_batches=False, now=MONDAY_6 + timedelta(minutes=30))
    assert not await report_due(sched, new_batches=False, now=MONDAY_6 + timedelta(hours=2))
    assert not await report_due(Schedule(model_id="mdl_c", cron="0 6 * * 1", report_types=["validation"]), True)


async def test_generate_stores_the_report() -> None:
    await seed()
    report = await generate("mdl_r")
    assert [r.report_id for r in await monitoring_reports("mdl_r")] == [report.report_id]


# ---------------------------------------------------------------------------------------------- API
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


async def test_report_on_request_over_http(client: TestClient) -> None:
    await seed()
    resp = client.post("/api/v1/monitoring/runs", headers=H, json={"model_id": "mdl_r", "report": True})
    assert resp.status_code == 202
    job = wait_job(client, resp.json()["data"]["job_id"])
    assert job["status"] == "succeeded", job
    listed = client.get("/api/v1/models/mdl_r/reports", headers=H, params={"type": "monitoring"}).json()
    items = listed["data"]["items"]
    assert len(items) == 1 and items[0]["rag_status"] == "red"
    page = client.get(f"/api/v1/models/mdl_r/reports/{items[0]['report_id']}", headers=H, params={"format": "html"})
    assert page.status_code == 200 and "Monitoring report" in page.text
