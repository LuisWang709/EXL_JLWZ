"""Monitoring report (HTML). Owner: A4.

A3's ``ReportBuilderImpl.build(ctx, "monitoring")`` delegates here; the monitoring timer and
``POST /api/v1/monitoring/runs {"report": true}`` call :func:`generate`, which also stores the report.

Content: overall status (= latest batch), the latest batch (score PSI, Gini against the baseline run, the most
drifted features and missing rates), the trend over all batches (chart + table), alerts and the thresholds from
config/pipeline.yaml. Same rule as A3's reports: every number is rendered through
:class:`mrf.reporting.numbers.Ledger` and re-checked with :func:`check_numbers`; a report with a mismatched or
untraceable number is refused. The trend chart is drawn from those same facts and is left out of the text check
(its numbers sit in SVG coordinates, not in the text).
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from markupsafe import Markup

from mrf.config import REPO_ROOT
from mrf.contracts.agents import StepContext
from mrf.contracts.models import Alert, ModelRecord, MonitoringMetric, Report, Run, Schedule
from mrf.core import MRFCode, MRFError
from mrf.core.ids import new_id
from mrf.monitoring.drift import SCORE_KEY, thresholds
from mrf.monitoring.registrar import TAG_BASELINE_RUN
from mrf.reporting.numbers import Ledger, check_numbers
from mrf.storage import Collections, get_blobs, get_repo

log = logging.getLogger(__name__)

TOP_FEATURES = 8
MAX_ALERTS = 20
STATUS_ORDER = {"green": 0, "amber": 1, "red": 2}
_SVG = re.compile(r"<svg\b.*?</svg>", re.S)
_COLORS = {"green": "#2e8b57", "amber": "#d08c00", "red": "#c0392b"}


def _stamp(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def psi_status(value: float, policy: dict[str, Any]) -> str:
    if value > float(policy["psi_red"]):
        return "red"
    if value >= float(policy["psi_amber"]):
        return "amber"
    return "green"


async def gather(model: ModelRecord) -> dict[str, Any]:
    repo = get_repo()
    metrics = await repo.find(
        Collections.METRICS, MonitoringMetric, where={"model_id": model.model_id}, page_size=10_000, order_by="at"
    )
    alerts: list[Alert] = []
    page = 1
    while True:
        chunk = await repo.find(
            Collections.ALERTS, Alert, where={"model_id": model.model_id}, page=page,
            page_size=100, order_by="-created_at",
        )
        alerts.extend(chunk.items)
        if page * 100 >= chunk.pagination.total or not chunk.items:
            break
        page += 1
    schedule = await repo.get_or_none(Collections.SCHEDULES, model.model_id, Schedule)
    run_id = model.tags.get(TAG_BASELINE_RUN)
    baseline_run = await repo.get_or_none(Collections.RUNS, run_id, Run) if run_id else None
    gini = (baseline_run.metrics if baseline_run else {}).get("gini")
    return {
        "metrics": sorted(metrics.items, key=lambda m: m.at),
        "alerts": alerts,
        "schedule": schedule,
        "baseline_gini": float(gini) if isinstance(gini, int | float) and not isinstance(gini, bool) else None,
        "baseline_run_id": run_id,
    }


def assemble(
    model: ModelRecord, data: dict[str, Any], policy: dict[str, Any] | None = None
) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    """facts (key -> number), sources (key -> where it came from), view (everything else the template needs)."""
    policy = policy or thresholds()
    metrics: list[MonitoringMetric] = data["metrics"]
    alerts: list[Alert] = data["alerts"]
    facts: dict[str, Any] = {}
    sources: dict[str, str] = {}

    def put(key: str, value: Any, source: str) -> None:
        if value is not None:
            facts[key] = value
            sources[key] = source

    for name in ("psi_amber", "psi_red", "gini_drop_red", "missing_rate_amber", "missing_rate_red"):
        put(f"thresholds.{name}", float(policy[name]), f"config/pipeline.yaml:monitoring.{name}")

    batches: list[dict[str, Any]] = []
    for i, m in enumerate(metrics):
        src = f"monitoring_metrics:{m.model_id}:{m.batch_id}"
        features = {k: v for k, v in m.psi.items() if k != SCORE_KEY}
        worst = max(features.items(), key=lambda kv: kv[1]) if features else None
        put(f"batch.{i}.rows", m.row_count, src)
        put(f"batch.{i}.psi_score", m.psi.get(SCORE_KEY), src)
        put(f"batch.{i}.max_feature_psi", worst[1] if worst else None, src)
        put(f"batch.{i}.gini", m.gini, src)
        put(f"batch.{i}.max_missing", max(m.missing_rate.values()) if m.missing_rate else None, src)
        batches.append(
            {
                "i": i,
                "batch_id": m.batch_id,
                "at": _stamp(m.at),
                "status": m.status,
                "worst": worst[0] if worst else None,
            }
        )

    counts = {s: sum(1 for m in metrics if m.status == s) for s in STATUS_ORDER}
    put("summary.batches", len(metrics), "monitoring_metrics")
    for status, n in counts.items():
        put(f"summary.{status}", n, "monitoring_metrics")
    put("summary.alerts_open", sum(1 for a in alerts if a.status != "closed"), "alerts.status != closed")
    put("summary.alerts_unacknowledged", sum(1 for a in alerts if not a.acknowledged), "alerts.acknowledged == false")

    latest = metrics[-1] if metrics else None
    top: list[dict[str, Any]] = []
    findings: list[str] = []
    if latest is not None:
        src = f"monitoring_metrics:{latest.model_id}:{latest.batch_id}"
        ranked = sorted(((k, v) for k, v in latest.psi.items() if k != SCORE_KEY), key=lambda kv: -kv[1])
        for name, value in ranked[:TOP_FEATURES]:
            put(f"latest.feature.{name}.psi", value, src)
            put(f"latest.feature.{name}.missing", latest.missing_rate.get(name), src)
            top.append({"name": name, "status": psi_status(value, policy)})
        put("baseline.gini", data["baseline_gini"], f"runs:{data['baseline_run_id']}")
        if latest.gini is not None and data["baseline_gini"] is not None:
            put("latest.gini_drop", data["baseline_gini"] - latest.gini, "baseline.gini - latest Gini")
        rejected = any(a.kind == "data_quality" and a.severity == "red" and
                       a.detail.get("batch_id") == latest.batch_id for a in alerts)
        if rejected:
            findings.append("The latest batch failed data quality checks; it did not trigger model re-validation.")
        elif latest.status == "red":
            findings.append(
                "The latest batch is red. The model needs re-validation; the monitoring job sends the pipeline back "
                "to the usability run when the model is in production."
            )
        elif latest.status == "amber":
            findings.append("The latest batch is amber: review drift, quality warnings and any unassessed dimensions.")
        else:
            findings.append("The latest batch is green: no material drift against the baseline.")
        if not latest.psi:
            findings.append("No drift was measured for the latest batch. Consult its alert evidence.")
        if data["baseline_gini"] is None:
            findings.append("No baseline Gini is recorded, so the performance comparison is not available.")
    else:
        findings.append("No monitoring batch has been processed for this model yet.")

    view = {
        "overall": latest.status if latest else None,
        "batches": batches,
        "latest": batches[-1] if batches else None,
        "top_features": top,
        "alerts": [
            {
                "at": _stamp(a.created_at),
                "severity": a.severity,
                "kind": a.kind,
                "message": a.message,
                "acknowledged": a.acknowledged,
                "status": a.status,
                "resolution": a.resolution,
                "handled_by": a.closed_by or a.acknowledged_by,
            }
            for a in alerts[:MAX_ALERTS]
        ],
        "schedule": data["schedule"],
        "findings": findings,
    }
    return facts, sources, view


def chart_svg(facts: dict[str, Any], view: dict[str, Any], width: int = 960, height: int = 260) -> Markup:
    """Score PSI and the largest feature PSI per batch, with the amber / red threshold lines."""
    batches = view["batches"]
    if not batches:
        return Markup("")
    amber, red = facts["thresholds.psi_amber"], facts["thresholds.psi_red"]
    series = {key: [facts.get(f"batch.{b['i']}.{key}") for b in batches] for key in ("psi_score", "max_feature_psi")}
    top = max([red * 1.4, *[v for vals in series.values() for v in vals if v is not None]])
    left, right, pad_top, bottom = 48, 16, 14, 34
    plot_w, plot_h = width - left - right, height - pad_top - bottom
    step = plot_w / max(len(batches) - 1, 1)

    def x(i: int) -> float:
        return left + (i * step if len(batches) > 1 else plot_w / 2)

    def y(v: float) -> float:
        return pad_top + plot_h * (1 - v / top)

    parts = [
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="PSI per batch">',
        f'<rect x="{left}" y="{pad_top}" width="{plot_w}" height="{plot_h}" fill="#fafbfd" stroke="#d5dae3"/>',
    ]
    for value, color, label in ((amber, _COLORS["amber"], "amber"), (red, _COLORS["red"], "red")):
        parts.append(
            f'<line x1="{left}" x2="{left + plot_w}" y1="{y(value):.1f}" y2="{y(value):.1f}" stroke="{color}" '
            f'stroke-dasharray="5 4"/><text x="{left + plot_w - 4}" y="{y(value) - 4:.1f}" text-anchor="end" '
            f'font-size="11" fill="{color}">{label} {value:.2f}</text>'
        )
    for key, color, dash in (("psi_score", "#1d4e89", ""), ("max_feature_psi", "#7a7f8c", ' stroke-dasharray="3 3"')):
        points = [(x(i), y(v)) for i, v in enumerate(series[key]) if v is not None]
        if len(points) > 1:
            path = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
            parts.append(f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="2"{dash}/>')
        for px, py in points:
            parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="{color}"/>')
    for b in batches:
        color = _COLORS.get(b["status"], "#7a7f8c")
        parts.append(
            f'<rect x="{x(b["i"]) - 5:.1f}" y="{pad_top + plot_h + 6}" width="10" height="10" rx="2" fill="{color}"/>'
            f'<text x="{x(b["i"]):.1f}" y="{height - 4}" text-anchor="middle" font-size="10" fill="#5b6475">'
            f"B{b['i'] + 1}</text>"
        )
    parts.append(
        f'<text x="{left - 6}" y="{pad_top + 10}" text-anchor="end" font-size="10" fill="#5b6475">{top:.2f}</text>'
        f'<text x="{left - 6}" y="{pad_top + plot_h}" text-anchor="end" font-size="10" fill="#5b6475">0</text>'
    )
    parts.append("</svg>")
    # built only from numbers, fixed strings and colours above - no user text goes into the SVG
    return Markup("".join(parts))  # noqa: S704  # nosec B704


def render(ledger: Ledger, view: dict[str, Any], model: ModelRecord, report_id: str) -> str:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

    env = Environment(
        loader=FileSystemLoader(REPO_ROOT / "templates"),
        autoescape=select_autoescape(enabled_extensions=("html", "j2")),
        undefined=StrictUndefined,
    )
    template = env.get_template("monitoring_report.html.j2")
    return template.render(
        num=ledger.num,
        has=ledger.has,
        view=view,
        model=model,
        chart=chart_svg(ledger.facts, view),
        report_id=report_id,
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    )


class MonitoringReportBuilder:
    """No-arg constructor, like every registry implementation."""

    async def build(self, ctx: StepContext) -> Report:
        model = await get_repo().get_or_none(Collections.MODELS, ctx.model.model_id, ModelRecord) or ctx.model
        data = await gather(model)
        facts, sources, view = assemble(model, data)
        report_id = new_id("report")
        ledger = Ledger(facts, sources)
        page = render(ledger, view, model, report_id)
        check = check_numbers(_SVG.sub(" ", page), facts)
        if not check["passed"]:
            raise MRFError(
                MRFCode.INTERNAL,
                f"monitoring report failed the number check: {len(check['mismatched'])} mismatched, "
                f"{len(check['untraceable'])} untraceable",
                detail=check,
            )
        ref = await get_blobs().put_bytes(
            f"reports/{model.model_id}/{report_id}.html",
            page.encode("utf-8"),
            media_type="text/html",
            filename=f"{report_id}.html",
        )
        latest = data["metrics"][-1] if data["metrics"] else None
        log.info("monitoring report %s for %s: %s", report_id, model.model_id, view["overall"])
        return Report(
            report_id=report_id,
            model_id=model.model_id,
            type="monitoring",
            artifact=ref,
            rag_status=view["overall"],
            summary={
                "overall": view["overall"],
                "latest_batch": latest.batch_id if latest else None,
                "batches": len(data["metrics"]),
                "findings": view["findings"],
                "metrics": {k: v for k, v in facts.items() if not k.startswith("thresholds.")},
                "number_check": check,
                "numbers": [{k: e[k] for k in ("key", "text", "source")} for e in ledger.entries],
                "sources": sources,
            },
        )


async def generate(model_id: str) -> Report:
    """Build and store a monitoring report for one model (timer, POST /monitoring/runs with report=true)."""
    repo = get_repo()
    model = await repo.get(Collections.MODELS, model_id, ModelRecord)
    report = await MonitoringReportBuilder().build(StepContext(pipeline_id=model.pipeline_id or "", model=model))
    await repo.put(Collections.REPORTS, report.report_id, report)
    return report
