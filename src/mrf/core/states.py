"""Pipeline states (plan section "流水线状态") and the allowed transitions.

The orchestrator (A1) is the only writer of ``Pipeline.state``. UI (A4) and API use
:data:`ALLOWED_TRANSITIONS` to reject illegal operations with MRF-3201.
"""

from __future__ import annotations

from enum import Enum


class PipelineState(str, Enum):
    RECEIVED = "received"
    CLASSIFIED = "classified"
    DOC_DRAFTING = "doc_drafting"
    DOC_RATING = "doc_rating"
    AWAITING_DOC_APPROVAL = "awaiting_doc_approval"  # H1
    REBUILDING = "rebuilding"
    PARITY_PASSED = "parity_passed"
    USABILITY_RUN = "usability_run"
    AWAITING_SIGNOFF = "awaiting_signoff"  # H2
    DEPLOYED = "deployed"
    MONITORING = "monitoring"
    # side states
    MANUAL_REVIEW = "manual_review"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {PipelineState.MONITORING, PipelineState.FAILED}

    @property
    def is_waiting_for_human(self) -> bool:
        return self in {
            PipelineState.AWAITING_DOC_APPROVAL,
            PipelineState.AWAITING_SIGNOFF,
            PipelineState.MANUAL_REVIEW,
        }


S = PipelineState

#: Happy path + retry loops + human-gate outcomes. Any non-terminal state may also go to
#: MANUAL_REVIEW or FAILED (added below).
ALLOWED_TRANSITIONS: dict[PipelineState, set[PipelineState]] = {
    S.RECEIVED: {S.CLASSIFIED},
    S.CLASSIFIED: {S.DOC_DRAFTING},
    S.DOC_DRAFTING: {S.DOC_RATING},
    S.DOC_RATING: {S.DOC_DRAFTING, S.AWAITING_DOC_APPROVAL},  # fail -> redraft with feedback
    S.AWAITING_DOC_APPROVAL: {S.REBUILDING, S.DOC_DRAFTING},  # approve / reject-with-comment
    S.REBUILDING: {S.REBUILDING, S.PARITY_PASSED},  # self-heal loop
    S.PARITY_PASSED: {S.USABILITY_RUN},
    S.USABILITY_RUN: {S.AWAITING_SIGNOFF},
    S.AWAITING_SIGNOFF: {S.DEPLOYED, S.REBUILDING, S.USABILITY_RUN},
    S.DEPLOYED: {S.MONITORING},
    S.MONITORING: {S.USABILITY_RUN},  # drift above threshold -> re-validation
    # a human can push a manual-review item back to any working step
    S.MANUAL_REVIEW: {
        S.CLASSIFIED,
        S.DOC_DRAFTING,
        S.AWAITING_DOC_APPROVAL,
        S.REBUILDING,
        S.USABILITY_RUN,
        S.FAILED,
    },
    S.FAILED: set(),
}

for _state, _targets in ALLOWED_TRANSITIONS.items():
    if _state not in {S.MANUAL_REVIEW, S.FAILED}:
        _targets.update({S.MANUAL_REVIEW, S.FAILED})


def can_transition(src: PipelineState, dst: PipelineState) -> bool:
    return dst in ALLOWED_TRANSITIONS[src]
