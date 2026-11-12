"""Job handlers for pipeline jobs (registered on import)."""

from __future__ import annotations

import logging
from typing import Any

from mrf.config import get_settings
from mrf.contracts.models import Gate, Job, Review, utcnow
from mrf.jobs import register_handler
from mrf.orchestrator.graph import RunOutcome
from mrf.orchestrator.service import get_orchestrator
from mrf.storage import Collections, get_repo

log = logging.getLogger(__name__)
MAX_AUTO_APPROVALS = 10


def _result(outcome: RunOutcome) -> dict[str, Any]:
    return {
        "pipeline_id": outcome.pipeline_id,
        "state": outcome.state.value,
        "waiting_for_review": outcome.interrupted,
        "review_id": outcome.review_id,
        "gate": outcome.gate,
    }


async def _auto_approve(outcome: RunOutcome) -> RunOutcome:
    """Local demo / CI only: approve H1 and H2 automatically (never manual-review items)."""
    orch, repo = await get_orchestrator(), get_repo()
    for _ in range(MAX_AUTO_APPROVALS):
        if not outcome.interrupted or outcome.gate not in {Gate.H1.value, Gate.H2.value} or not outcome.review_id:
            break
        review = await repo.get(Collections.REVIEWS, outcome.review_id, Review)
        review.status, review.decided_by, review.decided_at = "approved", "auto-approve", utcnow()
        review.comment = "auto-approved (MRF_ENV=local, options.auto_approve)"
        await repo.put(Collections.REVIEWS, review.review_id, review)
        outcome = await orch.resume(outcome.pipeline_id, {"decision": "approve", "operator": "auto-approve"})
    return outcome


def _auto_allowed(job: Job) -> bool:
    return bool(job.payload.get("auto_approve")) and get_settings().env == "local"


@register_handler("pipeline")
async def run_pipeline(job: Job) -> dict[str, Any]:
    orch = await get_orchestrator()
    outcome = await orch.start(job.resource["pipeline_id"])
    if _auto_allowed(job):
        outcome = await _auto_approve(outcome)
    return _result(outcome)


@register_handler("pipeline_resume")
async def resume_pipeline(job: Job) -> dict[str, Any]:
    orch = await get_orchestrator()
    outcome = await orch.resume(job.resource["pipeline_id"], job.payload["decision"])
    if _auto_allowed(job):
        outcome = await _auto_approve(outcome)
    return _result(outcome)


@register_handler("pipeline_reenter")
async def reenter_pipeline(job: Job) -> dict[str, Any]:
    orch = await get_orchestrator()
    outcome = await orch.reenter(
        job.resource["pipeline_id"], job.payload["node"], job.payload.get("feedback"), job.payload.get("artifacts")
    )
    return _result(outcome)
