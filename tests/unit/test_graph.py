"""State machine: every branch with stub agents (no LLM, in-memory storage)."""

from __future__ import annotations

from mrf.contracts.models import ArtifactRef, Pipeline, Review, Run
from mrf.core import PipelineState as S
from mrf.orchestrator.graph import Orchestrator
from mrf.orchestrator.registry import Registry
from mrf.orchestrator.service import create_pipeline
from mrf.orchestrator.stubs import StubClassifier, StubRater, StubRebuilder
from mrf.storage import Collections, get_repo

SRC = [ArtifactRef(uri="file:///x/m001.sas", filename="m001.sas")]


async def _new(orch_kwargs: dict | None = None) -> tuple[Orchestrator, str]:
    p, _ = await create_pipeline(model_name="M001", source_refs=SRC, dataset_ids=["ds_1"])
    return Orchestrator(registry=Registry.stubs(**(orch_kwargs or {}))), p.pipeline_id


async def _pipeline(pid: str) -> Pipeline:
    return await get_repo().get(Collections.PIPELINES, pid, Pipeline)


async def _approve(orch: Orchestrator, pid: str, review_id: str, **decision: object) -> object:
    repo = get_repo()
    r = await repo.get(Collections.REVIEWS, review_id, Review)
    r.status = "approved"
    await repo.put(Collections.REVIEWS, review_id, r)
    return await orch.resume(pid, {"decision": "approve", **decision})


async def test_happy_path_reaches_monitoring() -> None:
    orch, pid = await _new()
    out = await orch.start(pid)
    assert out.interrupted and out.gate == "H1" and out.state is S.AWAITING_DOC_APPROVAL
    out = await _approve(orch, pid, out.review_id)
    assert out.interrupted and out.gate == "H2" and out.state is S.AWAITING_SIGNOFF
    out = await _approve(orch, pid, out.review_id)
    assert not out.interrupted and out.state is S.MONITORING
    p = await _pipeline(pid)
    states = [t.to_state for t in p.history]
    assert states == [
        S.RECEIVED,
        S.CLASSIFIED,
        S.DOC_DRAFTING,
        S.DOC_RATING,
        S.AWAITING_DOC_APPROVAL,
        S.REBUILDING,
        S.PARITY_PASSED,
        S.USABILITY_RUN,
        S.AWAITING_SIGNOFF,
        S.DEPLOYED,
        S.MONITORING,
    ]
    runs = await get_repo().find(Collections.RUNS, Run, where={"dataset_id": "ds_1"})
    assert runs.pagination.total == 1


async def test_doc_retry_then_pass() -> None:
    orch, pid = await _new({"rater": StubRater(pass_on_attempt=3)})
    out = await orch.start(pid)
    assert out.gate == "H1"
    p = await _pipeline(pid)
    assert p.attempts["doc"] == 3
    assert [t.to_state for t in p.history].count(S.DOC_RATING) == 3


async def test_doc_exhausted_goes_to_manual_and_can_be_rejected() -> None:
    orch, pid = await _new({"rater": StubRater(pass_on_attempt=99)})
    out = await orch.start(pid)
    assert out.gate == "manual" and out.state is S.MANUAL_REVIEW
    p = await _pipeline(pid)
    assert p.last_error and p.last_error["code"] == "MRF-2101"
    out = await orch.resume(pid, {"decision": "reject", "comment": "give up"})
    assert out.state is S.FAILED and not out.interrupted


async def test_manual_approve_resets_attempts_and_retries() -> None:
    rater = StubRater(pass_on_attempt=99)
    orch, pid = await _new({"rater": rater})
    out = await orch.start(pid)
    rater.pass_on_attempt = 1  # human fixed the issue
    out = await _approve(orch, pid, out.review_id)
    assert out.gate == "H1"


async def test_parity_exhausted_after_five() -> None:
    orch, pid = await _new({"rebuilder": StubRebuilder(pass_on_attempt=6)})
    out = await orch.start(pid)
    out = await _approve(orch, pid, out.review_id)
    assert out.gate == "manual"
    p = await _pipeline(pid)
    assert p.attempts["parity"] == 5 and p.last_error["code"] == "MRF-3002"


async def test_h1_reject_redrafts_with_feedback() -> None:
    orch, pid = await _new()
    out = await orch.start(pid)
    out = await orch.resume(pid, {"decision": "reject", "comment": "mention 2008 crisis"})
    assert out.gate == "H1"
    p = await _pipeline(pid)
    assert [t.to_state for t in p.history].count(S.AWAITING_DOC_APPROVAL) == 2
    assert out.review_id is not None


async def test_low_confidence_manual_edit_continues() -> None:
    orch, pid = await _new({"classifier": StubClassifier(confidence=0.4)})
    out = await orch.start(pid)
    assert out.gate == "manual"
    p = await _pipeline(pid)
    assert p.last_error["code"] == "MRF-2002"
    out = await _approve(
        orch, pid, out.review_id, edits={"classification": {"algorithm": "scorecard"}}, decision="edit"
    )
    assert out.gate == "H1"


async def test_unexpected_exception_fails_pipeline() -> None:
    class Boom:
        async def draft(self, ctx: object) -> None:
            raise ValueError("kaboom")

    orch, pid = await _new({"doc_writer": Boom()})
    out = await orch.start(pid)
    assert out.state is S.FAILED
    assert (await _pipeline(pid)).last_error["code"] == "MRF-5000"


async def test_reenter_from_monitoring() -> None:
    orch, pid = await _new()
    out = await orch.start(pid)
    out = await _approve(orch, pid, out.review_id)
    out = await _approve(orch, pid, out.review_id)
    assert out.state is S.MONITORING
    out = await orch.reenter(pid, "usability_run", ["PSI 0.31"])
    assert out.gate == "H2" and out.state is S.AWAITING_SIGNOFF
