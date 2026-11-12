"""Analysis and validation reports - implements ``ReportBuilder`` (registry slot ``report_builder``). Owner: A3.

* ``analysis``: red/amber/green for consistency (parity), performance (Gini, calibration), stability (score PSI)
  and fairness (disparate impact across segments), plus process improvement (elapsed time, LLM cost, attempts,
  automation rate; savings only when a measured manual baseline is configured).
* ``validation``: the H2 sign-off pack - identification, documentation rating, parity, metrics, findings,
  recommendation and a sign-off checklist.
* ``monitoring`` belongs to A4: delegated to ``mrf.monitoring.report:MonitoringReportBuilder`` when it exists.

Numbers come only from stored pipeline objects (runs, rebuild, rating, pipeline usage) and config; every number
is rendered through :class:`mrf.reporting.numbers.Ledger` and re-checked after rendering - a report with a
mismatch or an untraceable number is not stored (MRF-5000 -> manual review). Thresholds: config/pipeline.yaml
``reporting`` and ``monitoring``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from mrf.config import REPO_ROOT, get_policy
from mrf.contracts.agents import StepContext
from mrf.contracts.models import Dataset, Document, Gate, ModelRecord, Pipeline, Rating, Rebuild, Report, Review, Run
from mrf.core import MRFCode, MRFError
from mrf.core.ids import new_id
from mrf.reporting.numbers import Ledger, check_numbers
from mrf.storage import Collections, Repository, get_blobs, get_repo

log = logging.getLogger(__name__)

STATUS_ORDER = {"green": 0, "amber": 1, "red": 2}
DIMENSIONS = ("consistency", "performance", "stability", "fairness")
SEGMENT_FIELDS = ("n", "bad_rate", "approval_rate", "adverse_impact_ratio", "tpr", "fpr")


def worst(statuses: list[str | None]) -> str | None:
    known = [s for s in statuses if s]
    return max(known, key=lambda s: STATUS_ORDER[s]) if known else None


@dataclass
class Inputs:
    model: ModelRecord
    pipeline: Pipeline | None = None
    document: Document | None = None
    rating: Rating | None = None
    rebuild: Rebuild | None = None
    runs: list[Run] = field(default_factory=list)
    reviews: list[Review] = field(default_factory=list)
    fairness: dict[str, Any] | None = None
    fairness_source: str = ""
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------------------------- gathering
async def _latest(repo: Repository, collection: str, model: type[Any], **where: Any) -> Any:
    page = await repo.find(collection, model, where=where, page_size=1)
    return page.items[0] if page.items else None


async def gather(ctx: StepContext) -> Inputs:
    repo = get_repo()
    pipeline = await repo.get_or_none(Collections.PIPELINES, ctx.pipeline_id, Pipeline)
    arts = {**(pipeline.artifacts if pipeline else {}), **ctx.artifacts}
    mid = ctx.model.model_id
    inp = Inputs(model=ctx.model, pipeline=pipeline)
    doc_id = arts.get("doc_id")
    inp.document = (
        await repo.get_or_none(Collections.DOCUMENTS, doc_id, Document)
        if doc_id
        else await _latest(repo, Collections.DOCUMENTS, Document, model_id=mid)
    )
    rating_id = arts.get("rating_id")
    if rating_id:
        inp.rating = await repo.get_or_none(Collections.RATINGS, rating_id, Rating)
    elif inp.document:
        inp.rating = await _latest(repo, Collections.RATINGS, Rating, doc_id=inp.document.doc_id)
    rb_id = arts.get("rebuild_id")
    inp.rebuild = (
        await repo.get_or_none(Collections.REBUILDS, rb_id, Rebuild)
        if rb_id
        else await _latest(repo, Collections.REBUILDS, Rebuild, model_id=mid)
    )
    run_ids = arts.get("run_ids") or []
    if run_ids:
        inp.runs = [r for r in [await repo.get_or_none(Collections.RUNS, i, Run) for i in run_ids] if r]
    else:
        inp.runs = (await repo.find(Collections.RUNS, Run, where={"model_id": mid}, page_size=5)).items
    if pipeline:
        inp.reviews = (
            await repo.find(Collections.REVIEWS, Review, where={"pipeline_id": pipeline.pipeline_id}, page_size=100)
        ).items
    await _fairness(inp, repo)
    return inp


def _output_frame(run: Run) -> Any:
    import pandas as pd

    from mrf.monitoring.frames import SCORE_COLUMNS, _local_uri

    for art in run.outputs:
        name = art.filename.lower()
        if not name.endswith((".csv", ".parquet")):
            continue
        df = pd.read_parquet(_local_uri(art.uri)) if name.endswith(".parquet") else pd.read_csv(_local_uri(art.uri))
        score = next((c for c in SCORE_COLUMNS if c in df.columns), None)
        if score:
            return df, score
    return None


async def _fairness(inp: Inputs, repo: Repository) -> None:
    """Fairness by segment: from run metrics if the runner computed it, else from run outputs + dataset."""
    from mrf import validation as v

    segment = str(get_policy()["reporting"]["fairness_segment_column"])
    target = (inp.model.classification.target if inp.model.classification else None) or "default_flag"
    for run in inp.runs:
        if isinstance(run.metrics.get("fairness"), dict):
            inp.fairness, inp.fairness_source = run.metrics["fairness"], f"run:{run.run_id}.metrics.fairness"
            return
    for run in inp.runs:
        try:
            found = await asyncio.to_thread(_output_frame, run)
            if found is None:
                continue
            out, score = found
            frame = out
            if segment not in out.columns or target not in out.columns:
                from mrf.monitoring.frames import load_frame

                ds = await repo.get(Collections.DATASETS, run.dataset_id, Dataset)
                data = await asyncio.to_thread(load_frame, ds)
                if len(data) != len(out) or segment not in data.columns or target not in data.columns:
                    continue
                frame = data.assign(**{score: out[score].to_numpy()})
            inp.fairness = await asyncio.to_thread(v.fairness, frame[target], frame[score], frame[segment])
            inp.fairness_source = f"run:{run.run_id} outputs ({score}) + dataset:{run.dataset_id} ({segment})"
            return
        except (MRFError, OSError, ValueError, KeyError) as exc:  # warnings stay number-free (number check)
            log.warning("fairness from run %s failed: %s", run.run_id, exc)
            inp.warnings.append(f"Fairness could not be computed from run {run.run_id} ({type(exc).__name__}).")
    if inp.fairness is None:
        inp.warnings.append(
            f"Fairness not assessed: no run output with scores, the target and the segment column '{segment}'."
        )


# ---------------------------------------------------------------------------------------------- assembling
def _metric(runs: list[Run], *names: str) -> tuple[float | None, str]:
    for run in runs:
        for name in names:
            value = run.metrics.get(name)
            if isinstance(value, int | float) and not isinstance(value, bool):
                return float(value), f"run:{run.run_id}.metrics.{name}"
            if isinstance(value, dict) and isinstance(value.get("p_value"), int | float):
                return float(value["p_value"]), f"run:{run.run_id}.metrics.{name}.p_value"
    return None, ""


def assemble(inp: Inputs) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    """(facts: key -> value, sources: key -> where it came from, view: statuses / texts for the template)."""
    policy = get_policy()
    rep, mon = policy["reporting"], policy["monitoring"]
    facts: dict[str, Any] = {}
    sources: dict[str, str] = {}

    def put(key: str, value: Any, source: str) -> None:
        if value is not None:
            facts[key] = value
            sources[key] = source

    for key, value, src in (
        ("thresholds.gini_green", rep["gini_green"], "config/pipeline.yaml:reporting.gini_green"),
        ("thresholds.gini_amber", rep["gini_amber"], "config/pipeline.yaml:reporting.gini_amber"),
        ("thresholds.hl_p_value_amber", rep["hl_p_value_amber"], "config/pipeline.yaml:reporting.hl_p_value_amber"),
        ("thresholds.di_green", rep["disparate_impact_green"], "config/pipeline.yaml:reporting.disparate_impact_green"),
        ("thresholds.di_amber", rep["disparate_impact_amber"], "config/pipeline.yaml:reporting.disparate_impact_amber"),
        ("thresholds.psi_amber", mon["psi_amber"], "config/pipeline.yaml:monitoring.psi_amber"),
        ("thresholds.psi_red", mon["psi_red"], "config/pipeline.yaml:monitoring.psi_red"),
        ("thresholds.parity_tolerance", policy["parity"]["abs_tolerance"], "config/pipeline.yaml:parity.abs_tolerance"),
        ("thresholds.pass_score", policy["rating"]["pass_score"], "config/pipeline.yaml:rating.pass_score"),
    ):
        put(key, float(value), src)

    statuses: dict[str, str | None] = dict.fromkeys(DIMENSIONS)
    warnings = list(inp.warnings)
    findings: list[str] = []
    cls = inp.model.classification
    if cls:
        put("identification.confidence", cls.confidence, f"model:{inp.model.model_id}.classification.confidence")

    # documentation
    if inp.rating:
        r = inp.rating
        src = f"rating:{r.rating_id}"
        put("documentation.rating_total", r.total, f"{src}.total")
        put("documentation.rule_score", r.rule_score, f"{src}.rule_score")
        put("documentation.llm_score", r.llm_score, f"{src}.llm_score")
        put("documentation.attempts", int(r.attempt), f"{src}.attempt")
        if not r.passed:
            findings.append("The latest documentation rating did not pass; H1 approval was not automatic.")
    else:
        warnings.append("No documentation rating found for this model.")

    # consistency (parity)
    rb = inp.rebuild
    if rb and rb.parity and rb.parity.detail.get("skipped"):
        warnings.append("No rebuild was needed (the source is already Python), so consistency was not assessed.")
    elif rb and rb.parity:
        par, src = rb.parity, f"rebuild:{rb.rebuild_id}.parity"
        put("parity.n_records", int(par.n_records), f"{src}.n_records")
        put("parity.n_mismatches", int(par.n_mismatches), f"{src}.n_mismatches")
        put("parity.max_abs_diff", par.max_abs_diff, f"{src}.max_abs_diff")
        put("parity.tolerance", par.tolerance, f"{src}.tolerance")
        put("parity.attempts", int(rb.attempt), f"rebuild:{rb.rebuild_id}.attempt")
        statuses["consistency"] = "green" if par.passed else "red"
        if not par.passed:
            findings.append("The Python rebuild does not reproduce the legacy scores within tolerance.")
    else:
        warnings.append("No rebuild with a parity result found; consistency not assessed.")

    # performance
    if any(run.metrics.get("stub") for run in inp.runs):
        warnings.append("Run metrics come from a stub runner (A2's ModelRunner not delivered): not real results.")
    for key, names in (
        ("performance.auc", ("auc",)),
        ("performance.gini", ("gini",)),
        ("performance.ks", ("ks",)),
        ("performance.brier", ("brier",)),
        ("performance.hl_p_value", ("hosmer_lemeshow", "hl_p_value")),
        ("stability.psi_score", ("psi_score", "psi")),
    ):
        value, src = _metric(inp.runs, *names)
        put(key, value, src)
    gini = facts.get("performance.gini")
    if gini is not None:
        statuses["performance"] = (
            "green" if gini >= rep["gini_green"] else "amber" if gini >= rep["gini_amber"] else "red"
        )
        hl = facts.get("performance.hl_p_value")
        if hl is not None and hl < rep["hl_p_value_amber"] and statuses["performance"] == "green":
            statuses["performance"] = "amber"
            findings.append("Calibration: the Hosmer-Lemeshow test rejects good fit at the configured level.")
        if statuses["performance"] != "green":
            findings.append(f"Performance is {statuses['performance']}: Gini is below the green threshold.")
    else:
        warnings.append("No Gini in the usability run metrics; performance not assessed.")
    psi = facts.get("stability.psi_score")
    if psi is not None:
        statuses["stability"] = "green" if psi < mon["psi_amber"] else "amber" if psi <= mon["psi_red"] else "red"
        if statuses["stability"] != "green":
            findings.append(f"Score stability is {statuses['stability']}: the population has shifted.")
    else:
        warnings.append("No score PSI in the usability run metrics; stability not assessed.")

    # fairness
    segments: list[str] = []
    if inp.fairness:
        f, src = inp.fairness, inp.fairness_source
        for name in ("disparate_impact", "max_tpr_gap", "max_fpr_gap", "threshold"):
            put(f"fairness.{name}", f.get(name), f"{src}.{name}")
        put("fairness.n", int(f["n"]) if f.get("n") is not None else None, f"{src}.n")
        for seg, values in (f.get("segments") or {}).items():
            segments.append(str(seg))
            for fld in SEGMENT_FIELDS:
                value = values.get(fld)
                put(
                    f"fairness.segments.{seg}.{fld}",
                    int(value) if fld == "n" and value is not None else value,
                    f"{src}.segments.{seg}.{fld}",
                )
        di = facts.get("fairness.disparate_impact")
        if di is not None:
            statuses["fairness"] = (
                "green"
                if di >= rep["disparate_impact_green"]
                else "amber"
                if di >= rep["disparate_impact_amber"]
                else "red"
            )
            if statuses["fairness"] != "green":
                findings.append(
                    f"Fairness is {statuses['fairness']}: approval rates differ across segments; review the segment "
                    "table and agree mitigation before sign-off."
                )

    # process improvement
    p = inp.pipeline
    if p:
        src = f"pipeline:{p.pipeline_id}"
        last = p.history[-1].at if p.history else p.updated_at
        elapsed = max((last - p.created_at).total_seconds(), 0.0) / 60
        put("process.elapsed_minutes", elapsed, f"{src}.history (first -> last transition)")
        for name in ("llm_calls", "prompt_tokens", "completion_tokens"):
            put(f"process.{name}", int(getattr(p.usage, name)), f"{src}.usage.{name}")
        put("process.cost_eur", p.usage.cost_eur, f"{src}.usage.cost_eur")
        put("process.doc_attempts", int(p.attempts.get("doc", 0)), f"{src}.attempts.doc")
        put("process.parity_attempts", int(p.attempts.get("parity", 0)), f"{src}.attempts.parity")
        system = sum(1 for t in p.history if t.actor == "system")
        put("process.transitions", len(p.history), f"{src}.history")
        if p.history:
            put("process.automation_rate", system / len(p.history), f"{src}.history (actor == system / all)")
        put(
            "process.manual_reviews",
            sum(1 for r in inp.reviews if r.gate == Gate.MANUAL),
            f"reviews where pipeline_id={p.pipeline_id} and gate=manual",
        )
        baseline, rate = rep.get("manual_baseline_hours"), rep.get("analyst_cost_eur_per_hour")
        if baseline is not None:
            put("process.baseline_hours", float(baseline), "config/pipeline.yaml:reporting.manual_baseline_hours")
            put("process.hours_saved", float(baseline) - elapsed / 60, "baseline_hours - elapsed_minutes / 60")
            if rate is not None:
                put("process.rate_eur", float(rate), "config/pipeline.yaml:reporting.analyst_cost_eur_per_hour")
                put(
                    "process.cost_saved_eur",
                    float(baseline) * float(rate) - p.usage.cost_eur,
                    "baseline_hours * analyst_cost_eur_per_hour - usage.cost_eur",
                )
        else:
            warnings.append(
                "Manual baseline not measured yet (config reporting.manual_baseline_hours): savings not computed."
            )

    overall = worst(list(statuses.values()))
    if statuses["consistency"] == "red" or (inp.rating is not None and not inp.rating.passed):
        recommendation = "Do not approve: fix the failed checks first."
    elif overall == "red":
        recommendation = "Do not approve: at least one dimension is red."
    elif overall == "amber" or None in statuses.values():
        recommendation = "Approve only with conditions: amber or unassessed dimensions need a documented decision."
    else:
        recommendation = "Ready for approval: all dimensions are green."
    view = {
        "statuses": statuses,
        "overall": overall,
        "findings": findings,
        "warnings": warnings,
        "recommendation": recommendation,
        "segments": segments,
        "fairness_reference": (inp.fairness or {}).get("reference_segment"),
    }
    return facts, sources, view


# ---------------------------------------------------------------------------------------------- rendering
def render(report_type: str, ledger: Ledger, view: dict[str, Any], inp: Inputs, report_id: str) -> str:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

    env = Environment(
        loader=FileSystemLoader(REPO_ROOT / "templates"),
        autoescape=select_autoescape(enabled_extensions=("html", "j2")),
        undefined=StrictUndefined,
    )
    template = env.get_template(f"{report_type}_report.html.j2")
    return template.render(
        num=ledger.num,
        has=ledger.has,
        view=view,
        model=inp.model,
        cls=inp.model.classification,
        document=inp.document,
        rating=inp.rating,
        rebuild=inp.rebuild,
        runs=inp.runs,
        pipeline=inp.pipeline,
        report_id=report_id,
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    )


class ReportBuilderImpl:
    """No-arg constructor: picked up automatically by the orchestrator registry."""

    async def build(self, ctx: StepContext, report_type: str) -> Report:
        if report_type == "monitoring":
            return await self._monitoring(ctx)
        return (await self.build_many(ctx, [report_type]))[0]

    async def build_many(self, ctx: StepContext, report_types: list[str]) -> list[Report]:
        """Render separate report views from one immutable set of facts and evidence."""
        for kind in report_types:
            if kind not in {"analysis", "validation"}:
                raise MRFError(MRFCode.INPUT_BODY, f"unknown report type {kind!r}", field="type")
        inp = await gather(ctx)
        facts, sources, view = assemble(inp)
        return [await self._build_view(ctx, kind, inp, facts, sources, view) for kind in report_types]

    async def _build_view(
        self, ctx: StepContext, report_type: str, inp: Inputs,
        facts: dict[str, Any], sources: dict[str, str], view: dict[str, Any],
    ) -> Report:
        report_id = new_id("report")
        ledger = Ledger(facts, sources)
        page = render(report_type, ledger, view, inp, report_id)
        check = check_numbers(page, facts)
        if not check["passed"]:
            raise MRFError(
                MRFCode.INTERNAL,
                f"{report_type} report failed the number check: {len(check['mismatched'])} mismatched, "
                f"{len(check['untraceable'])} untraceable",
                detail=check,
            )
        ref = await get_blobs().put_bytes(
            f"reports/{ctx.model.model_id}/{report_id}.html",
            page.encode("utf-8"),
            media_type="text/html",
            filename=f"{report_id}.html",
        )
        log.info(
            "%s report %s for %s: %s, %d numbers checked",
            report_type,
            report_id,
            ctx.model.model_id,
            view["overall"],
            check["numbers"],
        )
        return Report(
            report_id=report_id,
            model_id=ctx.model.model_id,
            type=report_type,  # type: ignore[arg-type]
            artifact=ref,
            rag_status=view["overall"],
            summary={
                "statuses": view["statuses"],
                "recommendation": view["recommendation"],
                "findings": view["findings"],
                "warnings": view["warnings"],
                "metrics": {k: v for k, v in facts.items() if not k.startswith("thresholds.")},
                "number_check": check,
                "numbers": [{k: e[k] for k in ("key", "text", "source")} for e in ledger.entries],
                "sources": sources,
                "revalidation_dataset_ids": ctx.artifacts.get("revalidation_dataset_ids", []),
            },
        )

    @staticmethod
    async def _monitoring(ctx: StepContext) -> Report:
        from mrf.monitoring.report import MonitoringReportBuilder

        report: Report = await MonitoringReportBuilder().build(ctx)
        return report
