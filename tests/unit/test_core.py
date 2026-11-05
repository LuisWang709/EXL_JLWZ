"""Contract tests for mrf.core - these lock API contract v1."""

from __future__ import annotations

import itertools

from mrf.core import ALLOWED_TRANSITIONS, MRFCode, MRFError, PipelineState, accepted, error, success
from mrf.core.states import can_transition


def test_every_code_has_http_status_and_message() -> None:
    for code in MRFCode:
        assert 200 <= code.http_status < 600
        assert code.default_message


def test_success_envelope_shape() -> None:
    env = success("rid", {"x": 1}).model_dump(mode="json")
    assert set(env) == {"request_id", "status", "code", "message", "data", "errors", "warnings"}
    assert env["status"] == "success" and env["code"] == "MRF-0000"
    assert env["errors"] == [] and env["warnings"] == []


def test_accepted_envelope_has_poll_link() -> None:
    env = accepted("rid", "job_1", extra={"pipeline_id": "pl_1"})
    assert env.status == "accepted" and env.code == "MRF-0202"
    assert env.data == {"job_id": "job_1", "poll": "/api/v1/jobs/job_1", "pipeline_id": "pl_1"}


def test_error_envelope_always_has_errors_array() -> None:
    env = error("rid", MRFCode.NOT_FOUND)
    assert env.status == "error" and env.errors[0].code == "MRF-1404"


def test_mrf_error_carries_http_status() -> None:
    assert MRFError(MRFCode.INVALID_STATE).http_status == 409


def test_every_state_has_transition_entry() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(PipelineState)


def test_happy_path_is_allowed() -> None:
    path = [
        "received",
        "classified",
        "doc_drafting",
        "doc_rating",
        "awaiting_doc_approval",
        "rebuilding",
        "parity_passed",
        "usability_run",
        "awaiting_signoff",
        "deployed",
        "monitoring",
    ]
    states = [PipelineState(s) for s in path]
    for src, dst in itertools.pairwise(states):
        assert can_transition(src, dst), (src, dst)


def test_cannot_deploy_without_signoff() -> None:
    assert not can_transition(PipelineState.USABILITY_RUN, PipelineState.DEPLOYED)


def test_any_working_state_can_escalate() -> None:
    for s in PipelineState:
        if s not in {PipelineState.MANUAL_REVIEW, PipelineState.FAILED}:
            assert can_transition(s, PipelineState.MANUAL_REVIEW)
