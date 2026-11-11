"""A4 Streamlit UI: every page renders against the real API (in-memory storage) without an exception."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from mrf.api.app import create_app
from mrf.contracts.models import Gate, Pipeline, Review
from mrf.core.states import PipelineState
from mrf.monitoring.report import generate
from mrf.storage import Collections, get_repo
from mrf.ui.client import ApiClient
from tests.unit.test_monitoring_report import seed

APP = str(Path(__file__).resolve().parents[2] / "src" / "mrf" / "ui" / "app.py")


@pytest.fixture
def api_client() -> Iterator[ApiClient]:
    with TestClient(create_app(mount_mcp=False)) as tc:
        yield ApiClient("http://testserver", "test-key", operator="tester", http=tc)


async def seeded() -> None:
    await seed("mdl_r")
    await generate("mdl_r")
    repo = get_repo()
    pipeline = Pipeline(pipeline_id="pl_r", model_id="mdl_r", state=PipelineState.AWAITING_DOC_APPROVAL)
    await repo.put(Collections.PIPELINES, pipeline.pipeline_id, pipeline)
    review = Review(review_id="rev_r", pipeline_id="pl_r", model_id="mdl_r", gate=Gate.H1, reason="approve the doc")
    await repo.put(Collections.REVIEWS, review.review_id, review)


def page_script(name: str) -> AppTest:
    def script(view: str) -> None:
        import importlib

        importlib.import_module(f"mrf.ui.views.{view}").page()

    return AppTest.from_function(script, args=(name,), default_timeout=30)


def run(at: AppTest, client: ApiClient) -> AppTest:
    at.session_state["api"] = client
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


async def test_sign_in_form_when_not_signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MRF_API_KEY", "test-key")
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception and at.title[0].value == "Model Risk Factory"
    assert len(at.text_input) == 2  # key + name; the URL is fixed when the container holds the key


async def test_app_opens_on_overview(api_client: ApiClient) -> None:
    await seeded()
    at = run(AppTest.from_file(APP, default_timeout=30), api_client)
    assert at.title[0].value == "Overview"
    assert [m.value for m in at.metric][:3] == ["1", "0", "1"]  # models, working, waiting for a person


@pytest.mark.parametrize(
    ("view", "title"),
    [("pipelines", "Pipelines"), ("reviews", "Review queue"), ("models", "Models"), ("monitoring", "Monitoring")],
)
async def test_pages_render(api_client: ApiClient, view: str, title: str) -> None:
    await seeded()
    at = run(page_script(view), api_client)
    assert at.title[0].value == title


async def test_monitoring_page_shows_drift(api_client: ApiClient) -> None:
    await seeded()
    at = run(page_script("monitoring"), api_client)
    assert any(m.label == "Batches" and m.value == "3" for m in at.metric)
    assert any("Score PSI" in m.label and m.value == "0.310" for m in at.metric)


async def test_reject_needs_a_comment(api_client: ApiClient) -> None:
    await seeded()
    at = run(page_script("reviews"), api_client)
    reject = next(b for b in at.button if b.label == "Reject")
    reject.click().run()
    assert any("Say what must change" in e.value for e in at.error)
