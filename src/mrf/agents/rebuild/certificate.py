"""Parity certificate: an HTML page bound to the code hash, stored as a blob and listed as a report."""

from __future__ import annotations

from datetime import UTC, datetime

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from mrf.agents.rebuild.fixtures import Fixture
from mrf.config import REPO_ROOT
from mrf.contracts.models import ArtifactRef, ModelRecord, Rebuild, Report
from mrf.core.ids import new_id
from mrf.storage import Collections, get_blobs, get_repo

GENERATOR_LABELS = {
    "llm": "LLM translation of the legacy source (verified by this parity run)",
    "template": "deterministic transcription of the legacy parameter estimates",
}


def render_certificate(model: ModelRecord, rebuild: Rebuild, fixture: Fixture) -> str:
    assert rebuild.parity is not None and rebuild.code is not None  # noqa: S101 - caller guarantees a passed parity
    env = Environment(
        loader=FileSystemLoader(REPO_ROOT / "templates"),
        autoescape=select_autoescape(enabled_extensions=("html", "j2")),
        undefined=StrictUndefined,
    )
    detail = rebuild.parity.detail
    spec = {"n_numeric_terms": 0, "n_categorical_terms": 0, "categorical_columns": [], **(detail.get("spec") or {})}
    max_diff = rebuild.parity.max_abs_diff
    return env.get_template("parity_certificate.html.j2").render(
        model=model,
        rebuild=rebuild,
        parity=rebuild.parity,
        manifest=fixture.manifest,
        fixture_id=fixture.fixture_id,
        score_column=fixture.score_column,
        link=fixture.link,
        spec=spec,
        notes=detail.get("notes") or [],
        source_language=str(detail.get("source_language") or "legacy").upper(),
        generator_label=GENERATOR_LABELS.get(str(detail.get("generator")), str(detail.get("generator"))),
        max_abs_diff="n/a" if max_diff is None else f"{max_diff:.3g}",
        tolerance=f"{rebuild.parity.tolerance:g}" if rebuild.parity.tolerance is not None else "n/a",
        issued_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    )


async def issue_certificate(model: ModelRecord, rebuild: Rebuild, fixture: Fixture) -> ArtifactRef:
    page = render_certificate(model, rebuild, fixture)
    ref = await get_blobs().put_bytes(
        f"rebuilds/{model.model_id}/{rebuild.rebuild_id}/parity_certificate.html",
        page.encode("utf-8"),
        media_type="text/html",
        filename="parity_certificate.html",
    )
    assert rebuild.parity is not None  # noqa: S101
    report = Report(
        report_id=new_id("report"),
        model_id=model.model_id,
        type="parity_certificate",
        artifact=ref,
        rag_status="green",
        summary={
            "rebuild_id": rebuild.rebuild_id,
            "n_records": rebuild.parity.n_records,
            "n_mismatches": rebuild.parity.n_mismatches,
            "max_abs_diff": rebuild.parity.max_abs_diff,
            "tolerance": rebuild.parity.tolerance,
            "attempt": rebuild.attempt,
            "code_sha256": rebuild.code.sha256 if rebuild.code else None,
        },
    )
    await get_repo().put(Collections.REPORTS, report.report_id, report)
    return ref
