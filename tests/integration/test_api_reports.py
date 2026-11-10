"""Reports API (shared A3/A4 router): list with type filter, get summary or HTML artifact, 404s."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mrf.api.app import create_app
from mrf.contracts.models import Report
from mrf.reporting.builder import ReportBuilderImpl
from mrf.storage import Collections, get_repo
from tests.conftest import API_HEADERS as H
from tests.unit.test_report_builder import _pipeline_ctx


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def test_list_get_and_html(client: TestClient, tmp_path: Path) -> None:
    async def setup() -> tuple[str, list[str]]:
        ctx = await _pipeline_ctx(tmp_path)
        ids = []
        for kind in ("analysis", "validation"):
            report = await ReportBuilderImpl().build(ctx, kind)
            await get_repo().put(Collections.REPORTS, report.report_id, report)
            ids.append(report.report_id)
        monitoring = Report(report_id="rpt_mon", model_id=ctx.model.model_id, type="monitoring", rag_status="green")
        await get_repo().put(Collections.REPORTS, monitoring.report_id, monitoring)
        return ctx.model.model_id, ids

    mid, (analysis_id, validation_id) = asyncio.run(setup())
    all_reports = client.get(f"/api/v1/models/{mid}/reports", headers=H).json()["data"]
    assert all_reports["pagination"]["total"] == 3
    only = client.get(f"/api/v1/models/{mid}/reports?type=validation", headers=H).json()["data"]["items"]
    assert [r["report_id"] for r in only] == [validation_id]

    body = client.get(f"/api/v1/models/{mid}/reports/{analysis_id}", headers=H).json()["data"]
    assert body["type"] == "analysis" and body["summary"]["number_check"]["passed"]
    page = client.get(f"/api/v1/models/{mid}/reports/{analysis_id}?format=html", headers=H)
    assert page.headers["content-type"].startswith("text/html") and "Analysis report" in page.text

    assert client.get(f"/api/v1/models/{mid}/reports/rpt_mon?format=html", headers=H).status_code == 404
    assert client.get(f"/api/v1/models/mdl_other/reports/{analysis_id}", headers=H).status_code == 404
    assert client.get(f"/api/v1/models/{mid}/reports?type=weekly", headers=H).status_code == 422
    assert client.get("/api/v1/models/mdl_nope/reports", headers=H).status_code == 404
