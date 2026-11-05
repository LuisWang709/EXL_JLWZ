"""Deterministic stand-ins for every Protocol in mrf.contracts.agents.

The orchestrator uses them until the real implementation exists (see registry.py), and
tests use their knobs to drive every branch of the state machine:

    StubRater(pass_on_attempt=3)        # fail twice, then pass
    StubRebuilder(pass_on_attempt=6)    # never reaches parity within 5 attempts
    StubClassifier(confidence=0.4)      # low confidence -> manual review
"""

from __future__ import annotations

from pathlib import PurePosixPath

from mrf.contracts.agents import StepContext
from mrf.contracts.models import (
    ClassificationResult,
    Document,
    Evidence,
    ModelLanguage,
    ParityResult,
    QualityReport,
    Rating,
    Rebuild,
    Report,
    Run,
)
from mrf.core.ids import new_id

_SUFFIX = {
    ".sas": ModelLanguage.SAS,
    ".r": ModelLanguage.R,
    ".py": ModelLanguage.PYTHON,
    ".ipynb": ModelLanguage.PYTHON,
}


class StubClassifier:
    def __init__(self, confidence: float = 0.9) -> None:
        self.confidence = confidence

    async def classify(self, ctx: StepContext) -> ClassificationResult:
        lang = ModelLanguage.UNKNOWN
        for f in ctx.source_files:
            lang = _SUFFIX.get(PurePosixPath(f.filename).suffix.lower(), lang)
        return ClassificationResult(
            language=lang,
            algorithm="logistic_regression",
            purpose="pd",
            confidence=self.confidence,
            needs_review=self.confidence < 0.7,
            evidence=[Evidence(source="code", ref=f"{f.filename}:1") for f in ctx.source_files[:1]],
            metadata={"stub": True},
        )


class StubDocWriter:
    async def draft(self, ctx: StepContext) -> Document:
        sections = {
            s: f"[stub] {s} for {ctx.model.name} (attempt {ctx.attempt})"
            for s in ("purpose_and_use", "data", "methodology", "assumptions_and_limitations")
        }
        if ctx.feedback:
            sections["assumptions_and_limitations"] += " | addressed: " + "; ".join(ctx.feedback)
        return Document(
            doc_id=new_id("document"),
            model_id=ctx.model.model_id,
            attempt=ctx.attempt,
            content_md="\n\n".join(f"## {k}\n{v}" for k, v in sections.items()),
            sections=sections,
        )


class StubRater:
    def __init__(self, pass_on_attempt: int = 1) -> None:
        self.pass_on_attempt = pass_on_attempt

    async def rate(self, ctx: StepContext, document: Document) -> Rating:
        passed = document.attempt >= self.pass_on_attempt
        rule, llm = (52.0, 34.0) if passed else (40.0, 25.0)
        return Rating(
            rating_id=new_id("rating"),
            doc_id=document.doc_id,
            attempt=document.attempt,
            rule_score=rule,
            llm_score=llm,
            total=rule + llm,
            passed=passed,
            comments=[] if passed else [f"[stub] attempt {document.attempt}: expand limitations section"],
        )


class StubRebuilder:
    def __init__(self, pass_on_attempt: int = 1) -> None:
        self.pass_on_attempt = pass_on_attempt

    async def rebuild(self, ctx: StepContext) -> Rebuild:
        passed = ctx.attempt >= self.pass_on_attempt
        parity = ParityResult(
            passed=passed,
            n_records=1000,
            n_mismatches=0 if passed else 17,
            max_abs_diff=0.0 if passed else 0.0123,
            tolerance=1e-6,
        )
        return Rebuild(
            rebuild_id=new_id("rebuild"),
            model_id=ctx.model.model_id,
            attempt=ctx.attempt,
            parity=parity,
            status="passed" if passed else "failed",
            feedback=[] if passed else [f"[stub] 17 records differ; check reference coding (attempt {ctx.attempt})"],
        )


class StubRunner:
    async def run(self, ctx: StepContext, dataset_id: str, kind: str = "usability") -> Run:
        return Run(
            run_id=new_id("run"),
            model_id=ctx.model.model_id,
            dataset_id=dataset_id,
            kind="batch" if kind == "batch" else "usability",
            status="succeeded",
            metrics={"stub": True, "gini": 0.52, "ks": 0.38, "psi_score": 0.03},
        )


class StubReportBuilder:
    async def build(self, ctx: StepContext, report_type: str) -> Report:
        return Report(
            report_id=new_id("report"),
            model_id=ctx.model.model_id,
            type=report_type,  # type: ignore[arg-type]
            rag_status="green",
            summary={"stub": True},
        )


class StubQualityChecker:
    async def check(self, dataset_id: str) -> QualityReport:
        return QualityReport(dataset_id=dataset_id, passed=True)


class StubMonitoringRegistrar:
    def __init__(self) -> None:
        self.registered: list[tuple[str, str | None]] = []

    async def register(self, ctx: StepContext, cron: str | None = None) -> None:
        self.registered.append((ctx.model.model_id, cron))
