"""A4 UI client: envelope handling, headers, uploads and errors (httpx.MockTransport, no server)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from mrf.ui.client import ApiClient, ApiError

seen: list[httpx.Request] = []


def envelope(data: Any, status: str = "success", code: str = "MRF-0000") -> dict[str, Any]:
    return {"request_id": "r", "status": status, "code": code, "message": "m", "data": data, "errors": []}


def handler(request: httpx.Request) -> httpx.Response:
    seen.append(request)
    path = request.url.path
    if path == "/api/v1/models":
        return httpx.Response(200, json=envelope({"items": [{"model_id": "mdl_1"}], "pagination": {"total": 7}}))
    if path == "/api/v1/pipelines" and request.method == "POST":
        return httpx.Response(202, json=envelope({"job_id": "job_1", "pipeline_id": "pl_1", "model_id": "mdl_1"}))
    if path == "/api/v1/models/mdl_1/rebuilds" and request.method == "POST":
        return httpx.Response(202, json=envelope({"job_id": "job_rb"}))
    if path == "/api/v1/reviews/rev_1/decision":
        return httpx.Response(200, json=envelope({"review": {"review_id": "rev_1"}}))
    if path.endswith("/reports/rpt_1"):
        return httpx.Response(200, text="<html>report</html>", headers={"content-type": "text/html"})
    if path == "/api/v1/monitoring/schedules/mdl_1":
        body = {"status": "error", "code": "MRF-3201", "message": "monitoring schedules apply to deployed models"}
        return httpx.Response(409, json=body)
    return httpx.Response(404, json={"status": "error", "code": "MRF-1404", "message": "Not Found"})


@pytest.fixture
def client() -> ApiClient:
    seen.clear()
    return ApiClient("http://api.test/", "secret", operator="Luis", transport=httpx.MockTransport(handler))


def test_paged_items_and_api_key(client: ApiClient) -> None:
    items, total = client.items("/api/v1/models")
    assert items == [{"model_id": "mdl_1"}] and total == 7
    assert seen[-1].headers["X-API-Key"] == "secret" and seen[-1].url.params["page_size"] == "100"


def test_upload_is_multipart(client: ApiClient) -> None:
    started = client.start_pipeline("M001", [("m001.sas", b"proc logistic;", "text/plain")], owner="risk")
    assert started["pipeline_id"] == "pl_1"
    body = seen[-1].content.decode()
    assert seen[-1].headers["content-type"].startswith("multipart/form-data")
    assert 'name="model_name"' in body and 'filename="m001.sas"' in body and "proc logistic;" in body


def test_decision_carries_operator(client: ApiClient) -> None:
    client.decide("rev_1", "reject", "fix section 3")
    request = seen[-1]
    assert request.headers["X-Operator"] == "Luis"
    assert json.loads(request.content) == {"decision": "reject", "comment": "fix section 3"}


def test_start_rebuild_sends_fixture_and_attempt_limit(client: ApiClient) -> None:
    assert client.start_rebuild("mdl_1", "m002", 2)["job_id"] == "job_rb"
    assert json.loads(seen[-1].content) == {"fixture_id": "m002", "max_attempts": 2}
    client.start_rebuild("mdl_1")
    assert json.loads(seen[-1].content) == {"max_attempts": 5}


def test_html_and_errors(client: ApiClient) -> None:
    assert client.report_html("mdl_1", "rpt_1") == "<html>report</html>"
    with pytest.raises(ApiError) as conflict:
        client.put_schedule("mdl_1", "0 6 * * 1", True)
    assert conflict.value.status == 409 and conflict.value.code == "MRF-3201"
    with pytest.raises(ApiError) as missing:
        client.rebuilds("nope")
    assert missing.value.message == "Not Found"


def test_unreachable_api() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ApiError) as err:
        ApiClient("http://down.test", "k", transport=httpx.MockTransport(down)).models()
    assert err.value.code == "NETWORK"


def test_interrupted_download_is_an_api_error() -> None:
    def disconnected(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("connection reset", request=request)

    client = ApiClient("http://api.test", "k", transport=httpx.MockTransport(disconnected))
    with pytest.raises(ApiError) as err:
        client.report_html("model", "report")
    assert err.value.code == "NETWORK"


def test_error_keeps_request_id_for_support() -> None:
    def error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json=envelope(None, "error", "MRF-3201"))

    client = ApiClient("http://api.test", "k", transport=httpx.MockTransport(error))
    with pytest.raises(ApiError) as err:
        client.model("m")
    assert err.value.request_id == "r"


# ---------------------------------------------------------------------------------------------- cache
def _count(path: str) -> int:
    return sum(1 for r in seen if r.url.path == path)


def test_lists_are_cached_and_writes_clear_the_cache(client: ApiClient) -> None:
    client.models()
    client.models()
    assert _count("/api/v1/models") == 1  # second call served from the cache
    client.start_pipeline("M001", [("m001.sas", b"x", "text/plain")])
    client.models()
    assert _count("/api/v1/models") == 2  # a POST empties the cache


def test_fresh_bypasses_the_cache_and_errors_are_not_cached(client: ApiClient) -> None:
    client.models()
    with client.fresh():
        client.models()
    assert _count("/api/v1/models") == 2
    for _ in range(2):
        with pytest.raises(ApiError):
            client.rebuilds("nope")
    assert _count("/api/v1/models/nope/rebuilds") == 2


def test_warm_runs_calls_in_parallel_and_fills_the_cache(client: ApiClient) -> None:
    client.warm([client.models, lambda: client.rebuilds("nope")])  # the failing call is ignored here
    client.models()
    assert _count("/api/v1/models") == 1
    assert client.report_html("mdl_1", "rpt_1") == client.report_html("mdl_1", "rpt_1")
    assert _count("/api/v1/models/mdl_1/reports/rpt_1") == 1  # stored HTML is immutable
