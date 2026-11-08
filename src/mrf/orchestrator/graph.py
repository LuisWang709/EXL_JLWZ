"""LangGraph pipeline: nodes, retry routing, human gates. Owner: A1.

Nodes only (1) build a StepContext, (2) call a Protocol from the Registry, (3) persist the
returned object, (4) record the state transition, (5) route with ``Command(goto=...)``.
Big objects live in the Repository; the graph state only holds ids and counters.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from mrf.config import get_policy
from mrf.contracts.agents import StepContext
from mrf.contracts.models import (
    ClassificationResult,
    Document,
    Gate,
    ModelRecord,
    Pipeline,
    Review,
    StateTransition,
    utcnow,
)
from mrf.core import MRFCode, MRFError, PipelineState
from mrf.core.ids import new_id
from mrf.core.states import can_transition
from mrf.llm.usage import add_usage, track_usage
from mrf.orchestrator.registry import Registry
from mrf.storage import Collections, Repository, get_repo

log = logging.getLogger(__name__)
S = PipelineState

#: codes that count as one failed attempt of a retryable step (then normal retry routing)
RETRYABLE = {
    MRFCode.PARITY_FAILED,
    MRFCode.LLM_TIMEOUT,
    MRFCode.LLM_RATE_LIMIT,
    MRFCode.LLM_BAD_OUTPUT,
}

#: manual-review target_state -> node to resume at
TARGET_NODES: dict[PipelineState, str] = {
    S.CLASSIFIED: "accept_classification",
    S.DOC_DRAFTING: "doc_draft",
    S.AWAITING_DOC_APPROVAL: "gate_h1",
    S.REBUILDING: "rebuild",
    S.USABILITY_RUN: "usability_run",
}
#: failed step -> default resume node after a manual approve
DEFAULT_RESUME: dict[str, str] = {
    "classify": "accept_classification",
    "doc_draft": "doc_draft",
    "doc_rate": "doc_draft",
    "rebuild": "rebuild",
    "usability_run": "usability_run",
    "validation_report": "usability_run",
}
STEP_ATTEMPT_KEY = {"doc_draft": "doc", "doc_rate": "doc", "rebuild": "parity"}
NODES = (
    "entry",
    "classify",
    "accept_classification",
    "doc_draft",
    "doc_rate",
    "gate_h1",
    "rebuild",
    "usability_run",
    "validation_report",
    "gate_h2",
    "deploy",
    "register_monitoring",
    "escalate",
)


class GraphState(TypedDict, total=False):
    pipeline_id: str
    model_id: str
    attempts: dict[str, int]
    feedback: list[str]
    artifacts: dict[str, Any]
    resume_target: str | None
    failed_step: str | None
    reason_code: str | None
    reason: str | None


@dataclass
class RunOutcome:
    pipeline_id: str
    state: PipelineState
    interrupted: bool
    review_id: str | None = None
    gate: str | None = None


NodeFn = Callable[[GraphState], Awaitable[Command[Any]]]


class Orchestrator:
    def __init__(
        self,
        registry: Registry | None = None,
        repo: Repository | None = None,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
    ) -> None:
        self.registry = registry or Registry.discover()
        self.repo = repo or get_repo()
        policy = get_policy()
        self.doc_max = int(policy["retries"]["doc_quality_max_attempts"])
        self.parity_max = int(policy["retries"]["parity_max_attempts"])
        self.min_conf = float(policy["classification"]["min_confidence"])
        self.graph = self._build().compile(checkpointer=checkpointer or InMemorySaver())

    # ================================================================== public API
    async def start(self, pipeline_id: str) -> RunOutcome:
        p = await self._pipeline(pipeline_id)
        init: GraphState = {
            "pipeline_id": pipeline_id,
            "model_id": p.model_id,
            "attempts": {},
            "feedback": [],
            "artifacts": {},
            "resume_target": None,
        }
        return await self._invoke(pipeline_id, init)

    async def resume(self, pipeline_id: str, decision: dict[str, Any]) -> RunOutcome:
        """Continue after a human decision (H1 / H2 / manual)."""
        return await self._invoke(pipeline_id, Command(resume=decision))

    async def reenter(self, pipeline_id: str, node: str, feedback: list[str] | None = None) -> RunOutcome:
        """Start a new run of the thread at ``node`` (drift re-validation, lost checkpoint)."""
        if node not in NODES:
            raise MRFError(MRFCode.INPUT_BODY, f"unknown node {node!r}")
        snap = await self.graph.aget_state(self._cfg(pipeline_id))
        prev: dict[str, Any] = dict(snap.values) if snap and snap.values else {}
        p = await self._pipeline(pipeline_id)
        init: GraphState = {
            "pipeline_id": pipeline_id,
            "model_id": p.model_id,
            "attempts": dict(prev.get("attempts") or p.attempts),
            "feedback": feedback or [],
            "artifacts": dict(prev.get("artifacts") or {}),
            "resume_target": node,
        }
        return await self._invoke(pipeline_id, init)

    # ================================================================== graph
    def _build(self) -> StateGraph[GraphState]:
        g: StateGraph[GraphState] = StateGraph(GraphState)
        for name in NODES:
            g.add_node(name, self._guard(name, getattr(self, f"n_{name}")))  # type: ignore[call-overload]
        g.add_edge(START, "entry")
        return g

    @staticmethod
    def _cfg(pipeline_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": pipeline_id}, "recursion_limit": 100}

    async def _invoke(self, pipeline_id: str, payload: Any) -> RunOutcome:
        result = await self.graph.ainvoke(payload, self._cfg(pipeline_id))
        p = await self._pipeline(pipeline_id)
        interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
        if interrupts:
            value = interrupts[0].value or {}
            return RunOutcome(pipeline_id, p.state, True, value.get("review_id"), value.get("gate"))
        return RunOutcome(pipeline_id, p.state, False)

    def _guard(self, name: str, fn: NodeFn) -> NodeFn:
        """Usage accounting + last-resort error handling for every node."""

        async def node(state: GraphState) -> Command[Any]:
            pid = state["pipeline_id"]
            with track_usage() as usage:
                try:
                    return await fn(state)
                except GraphBubbleUp:  # interrupt() - not an error
                    raise
                except MRFError as exc:
                    if name == "escalate":
                        raise RuntimeError(f"escalation failed: {exc}") from exc
                    log.warning("node %s escalates %s", name, exc.code.value)
                    return await self._to_escalate(state, name, exc.code, exc.message)
                except Exception as exc:
                    log.exception("node %s crashed", name)
                    await self._transition(
                        pid,
                        S.FAILED,
                        step=name,
                        code=MRFCode.INTERNAL.value,
                        note=f"{type(exc).__name__}: {exc}"[:500],
                        last_error={"code": MRFCode.INTERNAL.value, "message": str(exc)[:500]},
                    )
                    return Command(goto=END)
                finally:
                    if usage.llm_calls or usage.backoff_retries:
                        p = await self._pipeline(pid)
                        add_usage(p.usage, usage)
                        await self.repo.put(Collections.PIPELINES, pid, p)

        node.__name__ = f"n_{name}"
        return node

    # ================================================================== nodes
    async def n_entry(self, s: GraphState) -> Command[Any]:
        return Command(goto=s.get("resume_target") or "classify", update={"resume_target": None})

    async def n_classify(self, s: GraphState) -> Command[Any]:
        ctx = await self._ctx(s)
        result = await self.registry.classifier.classify(ctx)
        model = ctx.model
        model.classification = result
        model.updated_at = utcnow()
        await self.repo.put(Collections.MODELS, model.model_id, model)
        if result.needs_review or result.confidence < self.min_conf:
            return await self._to_escalate(
                s,
                "classify",
                MRFCode.MODEL_UNIDENTIFIED,
                f"confidence {result.confidence:.2f} < {self.min_conf}",
            )
        await self._transition(
            s["pipeline_id"],
            S.CLASSIFIED,
            step="classify",
            note=f"{result.language.value}/{result.algorithm} conf={result.confidence:.2f}",
        )
        return Command(goto="doc_draft", update={"attempts": {**s.get("attempts", {}), "doc": 0}, "feedback": []})

    async def n_accept_classification(self, s: GraphState) -> Command[Any]:
        """Manual review accepted (or corrected) the classification."""
        await self._transition(s["pipeline_id"], S.CLASSIFIED, step="classify", actor="human")
        return Command(goto="doc_draft", update={"attempts": {**s.get("attempts", {}), "doc": 0}, "feedback": []})

    async def n_doc_draft(self, s: GraphState) -> Command[Any]:
        n = s.get("attempts", {}).get("doc", 0) + 1
        await self._transition(
            s["pipeline_id"], S.DOC_DRAFTING, step="doc_draft", note=f"attempt {n}", attempts={"doc": n}
        )
        ctx = await self._ctx(s, attempt=n)
        try:
            doc = await self.registry.doc_writer.draft(ctx)
        except MRFError as exc:
            if exc.code in RETRYABLE:
                return self._retry_or_escalate(s, "doc", n, [exc.message], "doc_draft", MRFCode.DOC_RATING_EXHAUSTED)
            raise
        doc.attempt = n
        await self.repo.put(Collections.DOCUMENTS, doc.doc_id, doc)
        return Command(
            goto="doc_rate",
            update={
                "attempts": {**s.get("attempts", {}), "doc": n},
                "artifacts": {**s.get("artifacts", {}), "doc_id": doc.doc_id},
            },
        )

    async def n_doc_rate(self, s: GraphState) -> Command[Any]:
        n = s.get("attempts", {}).get("doc", 1)
        await self._transition(s["pipeline_id"], S.DOC_RATING, step="doc_rate", note=f"attempt {n}")
        doc = await self.repo.get(Collections.DOCUMENTS, s["artifacts"]["doc_id"], Document)
        ctx = await self._ctx(s, attempt=n)
        try:
            rating = await self.registry.rater.rate(ctx, doc)
        except MRFError as exc:
            if exc.code in RETRYABLE:
                return self._retry_or_escalate(s, "doc", n, [exc.message], "doc_draft", MRFCode.DOC_RATING_EXHAUSTED)
            raise
        await self.repo.put(Collections.RATINGS, rating.rating_id, rating)
        doc.status = "rated"
        await self.repo.put(Collections.DOCUMENTS, doc.doc_id, doc)
        artifacts = {**s.get("artifacts", {}), "rating_id": rating.rating_id}
        if rating.passed:
            await self._audit(s["pipeline_id"], "doc_rate", f"passed {rating.total:.0f}")
            return Command(goto="gate_h1", update={"artifacts": artifacts, "feedback": []})
        await self._audit(s["pipeline_id"], "doc_rate", f"failed {rating.total:.0f} veto={rating.veto_flags}")
        return self._retry_or_escalate(
            s,
            "doc",
            n,
            rating.comments or [f"score {rating.total:.0f} below pass"],
            "doc_draft",
            MRFCode.DOC_RATING_EXHAUSTED,
            {"artifacts": artifacts},
        )

    async def n_gate_h1(self, s: GraphState) -> Command[Any]:
        pid = s["pipeline_id"]
        await self._transition(pid, S.AWAITING_DOC_APPROVAL, step="gate_h1")
        arts = s.get("artifacts", {})
        review = await self._open_review(
            s,
            Gate.H1,
            anchor=str(arts.get("doc_id")),
            reason="Documentation passed rating; approval required (H1)",
            payload={"doc_id": arts.get("doc_id"), "rating_id": arts.get("rating_id")},
        )
        decision = interrupt({"review_id": review.review_id, "gate": Gate.H1.value})
        kind = decision.get("decision")
        if kind == "reject":
            return Command(
                goto="doc_draft",
                update={
                    "attempts": {**s.get("attempts", {}), "doc": 0},
                    "feedback": [decision.get("comment") or "rejected at H1"],
                },
            )
        doc = await self.repo.get(Collections.DOCUMENTS, arts["doc_id"], Document)
        if kind == "edit":
            sections = dict(doc.sections)
            sections.update((decision.get("edits") or {}).get("sections") or {})
            doc.sections = sections
            doc.content_md = "\n\n".join(f"## {k}\n{v}" for k, v in sections.items())
        doc.status = "approved"
        await self.repo.put(Collections.DOCUMENTS, doc.doc_id, doc)
        await self._set_lifecycle(s["model_id"], "documented")
        return Command(goto="rebuild", update={"attempts": {**s.get("attempts", {}), "parity": 0}, "feedback": []})

    async def n_rebuild(self, s: GraphState) -> Command[Any]:
        n = s.get("attempts", {}).get("parity", 0) + 1
        pid = s["pipeline_id"]
        await self._transition(pid, S.REBUILDING, step="rebuild", note=f"attempt {n}", attempts={"parity": n})
        ctx = await self._ctx(s, attempt=n)
        try:
            rb = await self.registry.rebuilder.rebuild(ctx)
        except MRFError as exc:
            if exc.code in RETRYABLE:
                return self._retry_or_escalate(s, "parity", n, [exc.message], "rebuild", MRFCode.PARITY_EXHAUSTED)
            raise
        rb.attempt = n
        await self.repo.put(Collections.REBUILDS, rb.rebuild_id, rb)
        artifacts = {**s.get("artifacts", {}), "rebuild_id": rb.rebuild_id}
        if rb.parity is not None and rb.parity.passed:
            await self._transition(
                pid,
                S.PARITY_PASSED,
                step="rebuild",
                note=f"{rb.parity.n_records} records, max diff {rb.parity.max_abs_diff}",
            )
            await self._set_lifecycle(s["model_id"], "rebuilt")
            return Command(
                goto="usability_run",
                update={"artifacts": artifacts, "feedback": [], "attempts": {**s.get("attempts", {}), "parity": n}},
            )
        return self._retry_or_escalate(
            s,
            "parity",
            n,
            rb.feedback or ["parity failed"],
            "rebuild",
            MRFCode.PARITY_EXHAUSTED,
            {"artifacts": artifacts},
        )

    async def n_usability_run(self, s: GraphState) -> Command[Any]:
        pid = s["pipeline_id"]
        await self._transition(pid, S.USABILITY_RUN, step="usability_run")
        p = await self._pipeline(pid)
        ctx = await self._ctx(s)
        run_ids: list[str] = []
        for ds in p.dataset_ids:
            run = await self.registry.runner.run(ctx, ds, "usability")
            await self.repo.put(Collections.RUNS, run.run_id, run)
            run_ids.append(run.run_id)
        if not p.dataset_ids:
            await self._audit(pid, "usability_run", "no dataset registered for this pipeline; run skipped")
        return Command(goto="validation_report", update={"artifacts": {**s.get("artifacts", {}), "run_ids": run_ids}})

    async def n_validation_report(self, s: GraphState) -> Command[Any]:
        ctx = await self._ctx(s)
        ids: dict[str, str] = {}
        for kind in ("analysis", "validation"):
            report = await self.registry.report_builder.build(ctx, kind)
            await self.repo.put(Collections.REPORTS, report.report_id, report)
            ids[f"{kind}_report_id"] = report.report_id
        return Command(goto="gate_h2", update={"artifacts": {**s.get("artifacts", {}), **ids}})

    async def n_gate_h2(self, s: GraphState) -> Command[Any]:
        pid = s["pipeline_id"]
        await self._transition(pid, S.AWAITING_SIGNOFF, step="gate_h2")
        arts = s.get("artifacts", {})
        review = await self._open_review(
            s,
            Gate.H2,
            anchor=str(arts.get("validation_report_id")),
            reason="Validation report ready; independent sign-off required (H2)",
            payload={k: arts.get(k) for k in ("rebuild_id", "run_ids", "analysis_report_id", "validation_report_id")},
        )
        decision = interrupt({"review_id": review.review_id, "gate": Gate.H2.value})
        if decision.get("decision") == "reject":
            return Command(
                goto="rebuild",
                update={
                    "attempts": {**s.get("attempts", {}), "parity": 0},
                    "feedback": [decision.get("comment") or "rejected at H2"],
                },
            )
        await self._set_lifecycle(s["model_id"], "validated")
        return Command(goto="deploy")

    async def n_deploy(self, s: GraphState) -> Command[Any]:
        await self._transition(s["pipeline_id"], S.DEPLOYED, step="deploy")
        await self._set_lifecycle(s["model_id"], "production")
        return Command(goto="register_monitoring")

    async def n_register_monitoring(self, s: GraphState) -> Command[Any]:
        await self.registry.monitoring.register(await self._ctx(s))
        await self._transition(s["pipeline_id"], S.MONITORING, step="register_monitoring")
        return Command(goto=END)

    async def n_escalate(self, s: GraphState) -> Command[Any]:
        pid = s["pipeline_id"]
        step = s.get("failed_step") or "unknown"
        code = s.get("reason_code")
        await self._transition(
            pid,
            S.MANUAL_REVIEW,
            step=step,
            code=code,
            note=s.get("reason"),
            last_error={"code": code, "message": s.get("reason"), "step": step},
        )
        attempts = s.get("attempts", {})
        review = await self._open_review(
            s,
            Gate.MANUAL,
            anchor=f"{step}:{code}",
            reason=s.get("reason") or "manual review",
            reason_code=code,
            payload={"failed_step": step, "attempts": attempts, "artifacts": s.get("artifacts", {})},
        )
        decision = interrupt({"review_id": review.review_id, "gate": Gate.MANUAL.value})
        if decision.get("decision") == "reject":
            await self._transition(pid, S.FAILED, step=step, actor="human", note=decision.get("comment"))
            return Command(goto=END)
        if decision.get("decision") == "edit" and (decision.get("edits") or {}).get("classification"):
            model = await self.repo.get(Collections.MODELS, s["model_id"], ModelRecord)
            base = model.classification.model_dump() if model.classification else {}
            base.update(decision["edits"]["classification"])
            base["needs_review"] = False
            model.classification = ClassificationResult.model_validate(base)
            await self.repo.put(Collections.MODELS, model.model_id, model)
        target = decision.get("target_state")
        node = TARGET_NODES.get(S(target)) if target else DEFAULT_RESUME.get(step, "doc_draft")
        if node is None:
            raise MRFError(MRFCode.INVALID_STATE, f"cannot resume at {target}")
        key = STEP_ATTEMPT_KEY.get(node)
        new_attempts = {**attempts, **({key: 0} if key else {})}
        feedback = [decision["comment"]] if decision.get("comment") else []
        return Command(
            goto=node,
            update={
                "attempts": new_attempts,
                "feedback": feedback,
                "failed_step": None,
                "reason_code": None,
                "reason": None,
            },
        )

    # ================================================================== helpers
    def _retry_or_escalate(
        self,
        s: GraphState,
        key: str,
        n: int,
        feedback: list[str],
        retry_node: str,
        exhausted: MRFCode,
        extra: dict[str, Any] | None = None,
    ) -> Command[Any]:
        limit = self.doc_max if key == "doc" else self.parity_max
        attempts = {**s.get("attempts", {}), key: n}
        if n < limit:
            return Command(goto=retry_node, update={"attempts": attempts, "feedback": feedback, **(extra or {})})
        return Command(
            goto="escalate",
            update={
                **(extra or {}),
                "attempts": attempts,
                "feedback": feedback,
                "failed_step": retry_node,
                "reason_code": exhausted.value,
                "reason": f"{exhausted.default_message}. Last feedback: {'; '.join(feedback)[:400]}",
            },
        )

    async def _to_escalate(self, s: GraphState, step: str, code: MRFCode, message: str) -> Command[Any]:
        return Command(
            goto="escalate",
            update={
                "failed_step": step,
                "reason_code": code.value,
                "reason": f"{code.default_message}: {message}"[:500],
            },
        )

    async def _pipeline(self, pipeline_id: str) -> Pipeline:
        return await self.repo.get(Collections.PIPELINES, pipeline_id, Pipeline)

    async def _ctx(self, s: GraphState, attempt: int = 1) -> StepContext:
        p = await self._pipeline(s["pipeline_id"])
        model = await self.repo.get(Collections.MODELS, p.model_id, ModelRecord)
        return StepContext(
            pipeline_id=p.pipeline_id,
            model=model,
            source_files=model.source_files,
            dataset_ids=p.dataset_ids,
            attempt=attempt,
            feedback=list(s.get("feedback") or []),
            artifacts=dict(s.get("artifacts") or {}),
        )

    async def _set_lifecycle(self, model_id: str, lifecycle: str) -> None:
        model = await self.repo.get(Collections.MODELS, model_id, ModelRecord)
        model.lifecycle = lifecycle  # type: ignore[assignment]
        model.updated_at = utcnow()
        await self.repo.put(Collections.MODELS, model_id, model)

    async def _transition(
        self,
        pipeline_id: str,
        to: PipelineState,
        *,
        step: str | None = None,
        actor: str = "system",
        code: str | None = None,
        note: str | None = None,
        attempts: dict[str, int] | None = None,
        last_error: dict[str, Any] | None = None,
    ) -> None:
        p = await self._pipeline(pipeline_id)
        if attempts:
            p.attempts.update(attempts)
        if step:
            p.current_step = step
        if last_error is not None:
            p.last_error = last_error
        if p.state != to:
            if not can_transition(p.state, to):
                raise RuntimeError(f"illegal transition {p.state.value} -> {to.value}")
            p.history.append(StateTransition(from_state=p.state, to_state=to, actor=actor, code=code, note=note))
            p.state = to
            await self._audit(
                pipeline_id, step or to.value, f"{p.history[-1].from_state} -> {to.value}", code=code, actor=actor
            )
        p.updated_at = utcnow()
        await self.repo.put(Collections.PIPELINES, pipeline_id, p)

    async def _audit(
        self, pipeline_id: str, step: str, message: str, *, code: str | None = None, actor: str = "system"
    ) -> None:
        entry = {
            "pipeline_id": pipeline_id,
            "step": step,
            "message": message,
            "code": code,
            "actor": actor,
            "created_at": utcnow().isoformat(),
        }
        await self.repo.put(Collections.AUDIT, new_id("audit"), entry)

    async def _open_review(
        self,
        s: GraphState,
        gate: Gate,
        *,
        anchor: str,
        reason: str,
        payload: dict[str, Any],
        reason_code: str | None = None,
    ) -> Review:
        """Idempotent: LangGraph re-runs the whole node on resume, so reuse the same review.

        The key includes the history length: a resume re-run sees the same history (the gate's
        transition is a no-op the second time), a later new visit to the gate sees a longer one.
        """
        p = await self._pipeline(s["pipeline_id"])
        key = f"{s['pipeline_id']}|{gate.value}|{anchor}|{len(p.history)}"
        digest = hashlib.sha1(key.encode(), usedforsecurity=False)
        review_id = f"rev_{digest.hexdigest()[:16]}"
        existing = await self.repo.get_or_none(Collections.REVIEWS, review_id, Review)
        if existing is not None:
            return existing
        review = Review(
            review_id=review_id,
            pipeline_id=s["pipeline_id"],
            model_id=s["model_id"],
            gate=gate,
            reason=reason,
            reason_code=reason_code,
            payload=payload,
        )
        await self.repo.put(Collections.REVIEWS, review_id, review)
        return review
