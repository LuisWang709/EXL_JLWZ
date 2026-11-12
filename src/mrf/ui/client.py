"""HTTP client for the UI: the API's envelope in, plain dicts out. Owner: A4.

No Streamlit and no storage imports here, so it is unit-tested with httpx.MockTransport.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class ApiError(Exception):
    status: int
    code: str
    message: str
    detail: Any = None

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class ApiClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        operator: str = "ui",
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        http: httpx.Client | None = None,
    ) -> None:
        """``http``: a ready client (tests pass FastAPI's TestClient); its headers get the API key."""
        self.base_url = base_url.rstrip("/")
        self.operator = operator
        self._http = http or httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport)
        self._http.headers["X-API-Key"] = api_key

    # ------------------------------------------------------------------------------------------ plumbing
    def _call(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        try:
            resp = self._http.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise ApiError(0, "NETWORK", f"API not reachable at {self.base_url}: {exc}") from exc
        try:
            body: dict[str, Any] = resp.json()
        except ValueError as exc:
            raise ApiError(resp.status_code, f"HTTP-{resp.status_code}", resp.text[:300]) from exc
        if resp.status_code >= 400 or body.get("status") == "error":
            errors = body.get("errors") or [{}]
            raise ApiError(resp.status_code, str(body.get("code", resp.status_code)), body.get("message", ""), errors)
        return body

    def data(self, method: str, path: str, **kw: Any) -> Any:
        return self._call(method, path, **kw).get("data")

    def text(self, path: str, **params: Any) -> str:
        resp = self._http.get(path, params=params)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = {}
            raise ApiError(resp.status_code, str(body.get("code", resp.status_code)), body.get("message", resp.text))
        return resp.text

    def items(self, path: str, **params: Any) -> tuple[list[dict[str, Any]], int]:
        """First page of a paged list (max 100 items) and the total."""
        params.setdefault("page_size", 100)
        page = self.data("GET", path, params={k: v for k, v in params.items() if v is not None}) or {}
        return list(page.get("items", [])), int(page.get("pagination", {}).get("total", 0))

    # ------------------------------------------------------------------------------------------ health
    def health(self) -> dict[str, Any]:
        return dict(self.data("GET", "/readyz"))

    # ------------------------------------------------------------------------------------------ pipelines
    def pipelines(self, state: str | None = None) -> list[dict[str, Any]]:
        return self.items("/api/v1/pipelines", state=state)[0]

    def pipeline(self, pipeline_id: str) -> dict[str, Any]:
        return dict(self.data("GET", f"/api/v1/pipelines/{pipeline_id}"))

    def start_pipeline(
        self,
        model_name: str,
        files: list[tuple[str, bytes, str]],
        owner: str | None = None,
        dataset_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        form: dict[str, Any] = {"model_name": model_name, **({"owner": owner} if owner else {})}
        if dataset_ids:
            form["dataset_ids"] = dataset_ids
        uploads = [("files", (name, content, ctype or "application/octet-stream")) for name, content, ctype in files]
        return dict(self.data("POST", "/api/v1/pipelines", data=form, files=uploads))

    def upload_dataset(
        self,
        filename: str,
        content: bytes,
        role: str = "other",
        schema_name: str | None = None,
        model_id: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        form = {"role": role, "name": name or filename}
        if schema_name:
            form["schema_name"] = schema_name
        if model_id:
            form["model_id"] = model_id
        upload = [("file", (filename, content, "application/octet-stream"))]
        return dict(self.data("POST", "/api/v1/datasets", data=form, files=upload))

    def datasets(self, model_id: str | None = None, role: str | None = None) -> list[dict[str, Any]]:
        return self.items("/api/v1/datasets", model_id=model_id, role=role)[0]

    def job(self, job_id: str) -> dict[str, Any]:
        return dict(self.data("GET", f"/api/v1/jobs/{job_id}"))

    def wait_job(self, job_id: str, timeout: float = 120.0, interval: float = 1.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            job = self.job(job_id)
            if job.get("status") in {"succeeded", "failed", "cancelled"} or time.monotonic() > deadline:
                return job
            time.sleep(interval)

    # ------------------------------------------------------------------------------------------ reviews
    def reviews(self, status: str | None = "pending", gate: str | None = None) -> list[dict[str, Any]]:
        return self.items("/api/v1/reviews", status=status, gate=gate)[0]

    def decide(
        self, review_id: str, decision: str, comment: str | None = None, target_state: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"decision": decision, "comment": comment or None}
        if target_state:
            body["target_state"] = target_state
        return dict(
            self.data("POST", f"/api/v1/reviews/{review_id}/decision", json=body, headers={"X-Operator": self.operator})
        )

    # ------------------------------------------------------------------------------------------ models
    def models(self) -> list[dict[str, Any]]:
        return self.items("/api/v1/models")[0]

    def model(self, model_id: str) -> dict[str, Any]:
        return dict(self.data("GET", f"/api/v1/models/{model_id}"))

    def documents(self, model_id: str) -> list[dict[str, Any]]:
        return self.items(f"/api/v1/models/{model_id}/documents")[0]

    def document_html(self, model_id: str, doc_id: str) -> str:
        return self.text(f"/api/v1/models/{model_id}/documents/{doc_id}", format="html")

    def ratings(self, model_id: str, doc_id: str) -> list[dict[str, Any]]:
        return self.items(f"/api/v1/models/{model_id}/documents/{doc_id}/ratings")[0]

    def rebuilds(self, model_id: str) -> list[dict[str, Any]]:
        return self.items(f"/api/v1/models/{model_id}/rebuilds")[0]

    def rebuild_code(self, model_id: str, rebuild_id: str) -> str:
        return self.text(f"/api/v1/models/{model_id}/rebuilds/{rebuild_id}", format="code")

    def rebuild_certificate(self, model_id: str, rebuild_id: str) -> str:
        return self.text(f"/api/v1/models/{model_id}/rebuilds/{rebuild_id}", format="certificate")

    def runs(self, model_id: str) -> list[dict[str, Any]]:
        return self.items(f"/api/v1/models/{model_id}/runs")[0]

    def reports(self, model_id: str, report_type: str | None = None) -> list[dict[str, Any]]:
        return self.items(f"/api/v1/models/{model_id}/reports", type=report_type)[0]

    def report_html(self, model_id: str, report_id: str) -> str:
        return self.text(f"/api/v1/models/{model_id}/reports/{report_id}", format="html")

    # ------------------------------------------------------------------------------------------ monitoring
    def metrics(self, model_id: str) -> list[dict[str, Any]]:
        return list((self.data("GET", f"/api/v1/monitoring/models/{model_id}/metrics") or {}).get("items", []))

    def alerts(self, model_id: str | None = None, acknowledged: bool | None = None) -> tuple[list[dict[str, Any]], int]:
        params: dict[str, Any] = {"model_id": model_id}
        if acknowledged is not None:
            params["acknowledged"] = str(acknowledged).lower()
        return self.items("/api/v1/monitoring/alerts", **params)

    def put_schedule(self, model_id: str, cron: str, enabled: bool) -> dict[str, Any]:
        body = {"cron": cron, "enabled": enabled}
        return dict(self.data("PUT", f"/api/v1/monitoring/schedules/{model_id}", json=body))

    def monitoring_run(self, model_id: str | None = None, report: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {"model_id": model_id, "report": report}
        return dict(self.data("POST", "/api/v1/monitoring/runs", json=body))
