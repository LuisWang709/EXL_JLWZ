"""Checkpoint loss: a new Orchestrator with an empty saver = the container restarted with local SQLite.

The Pipeline document (state, attempts, artifacts, last_error) and the Review (recorded decision) must be
enough to continue.
"""

from __future__ import annotations

from mrf.contracts.models import ArtifactRef, Pipeline, Review, ReviewDecision
from mrf.core import PipelineState as S
from mrf.orchestrator.graph import Orchestrator
from mrf.orchestrator.registry import Registry
from mrf.orchestrator.service import create_pipeline, decide_review
from mrf.orchestrator.stubs import StubRater
from mrf.storage import Collections, get_repo

SRC = [ArtifactRef(uri="file:///x/m001.sas", filename="m001.sas")]


def _orch(**kw: object) -> Orchestrator:
    return Orchestrator(registry=Registry.stubs(**kw))  # fresh InMemorySaver each time


async def _pipeline(pid: str) -> Pipeline:
    return await get_repo().get(Collections.PIPELINES, pid, Pipeline)


async def test_decision_after_restart_continues_from_stored_state() -> None:
    p, _ = await create_pipeline(model_name="M001", source_refs=SRC, dataset_ids=["ds_1"])
    out = await _orch().start(p.pipeline_id)
    assert out.gate == "H1"
    assert (await _pipeline(p.pipeline_id)).artifacts["doc_id"]  # mirrored outside the checkpoint

    await decide_review(out.review_id or "", ReviewDecision(decision="approve"), "albert")
    restarted = _orch()  # checkpoint lost
    out2 = await restarted.resume(p.pipeline_id, {"decision": "approve"})
    assert out2.gate == "H2" and out2.state is S.AWAITING_SIGNOFF
    states = [t.to_state for t in (await _pipeline(p.pipeline_id)).history]
    assert states.count(S.AWAITING_DOC_APPROVAL) == 1  # no duplicate gate visit


async def test_reject_recorded_on_review_wins_over_resume_value() -> None:
    p, _ = await create_pipeline(model_name="M001", source_refs=SRC)
    orch = _orch()
    out = await orch.start(p.pipeline_id)
    await decide_review(out.review_id or "", ReviewDecision(decision="reject", comment="add 2008 crisis"), "albert")
    out2 = await _orch().resume(p.pipeline_id, {"decision": "reject"})
    assert out2.gate == "H1"
    assert [t.to_state for t in (await _pipeline(p.pipeline_id)).history].count(S.AWAITING_DOC_APPROVAL) == 2


async def test_manual_review_after_restart_keeps_reason() -> None:
    p, _ = await create_pipeline(model_name="M001", source_refs=SRC)
    out = await _orch(rater=StubRater(pass_on_attempt=99)).start(p.pipeline_id)
    assert out.gate == "manual"
    await decide_review(out.review_id or "", ReviewDecision(decision="approve"), "albert")
    out2 = await _orch(rater=StubRater(pass_on_attempt=1)).resume(p.pipeline_id, {"decision": "approve"})
    assert out2.gate == "H1"


async def test_recovered_running_job_continues_instead_of_restarting() -> None:
    p, _ = await create_pipeline(model_name="M001", source_refs=SRC)
    pipeline = await _pipeline(p.pipeline_id)
    pipeline.state, pipeline.attempts = S.DOC_DRAFTING, {"doc": 1}  # crashed mid-drafting
    await get_repo().put(Collections.PIPELINES, p.pipeline_id, pipeline)
    out = await _orch().start(p.pipeline_id)
    assert out.gate == "H1"
    p2 = await _pipeline(p.pipeline_id)
    assert S.CLASSIFIED not in [t.to_state for t in p2.history]  # classification was not redone
    assert p2.attempts["doc"] == 2


async def test_start_on_finished_pipeline_is_noop() -> None:
    p, _ = await create_pipeline(model_name="M001", source_refs=SRC)
    pipeline = await _pipeline(p.pipeline_id)
    pipeline.state = S.MONITORING
    await get_repo().put(Collections.PIPELINES, p.pipeline_id, pipeline)
    out = await _orch().start(p.pipeline_id)
    assert out.state is S.MONITORING and not out.interrupted


async def test_review_stores_full_decision() -> None:
    p, _ = await create_pipeline(model_name="M001", source_refs=SRC)
    out = await _orch().start(p.pipeline_id)
    review, _ = await decide_review(out.review_id or "", ReviewDecision(decision="approve", comment="ok"), "a")
    stored = (await get_repo().get(Collections.REVIEWS, review.review_id, Review)).payload["decision"]
    assert stored["decision"] == "approve" and stored["operator"] == "a" and stored["comment"] == "ok"
