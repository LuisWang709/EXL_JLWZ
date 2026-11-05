"""Pipeline use-cases shared by the API, the CLI and A4's monitoring job. Owner: A1."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from mrf.config import get_settings
from mrf.contracts.models import ArtifactRef, Gate, Job, ModelRecord, Pipeline, Review, ReviewDecision, utcnow
from mrf.core import MRFCode, MRFError, PipelineState
from mrf.core.ids import new_id
from mrf.orchestrator.graph import TARGET_NODES, Orchestrator
from mrf.storage import Collections, get_blobs, get_repo

ALLOWED_SUFFIXES = {".sas", ".r", ".py", ".ipynb", ".txt", ".zip", ".egp", ".json", ".yaml", ".yml", ".md", ".csv"}


@dataclass
class UploadedFile:
    filename: str
    data: bytes
    media_type: str | None = None


def _check_file(f: UploadedFile) -> None:
    suffix = PurePosixPath(f.filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise MRFError(
            MRFCode.INPUT_FILE_TYPE,
            f"'{f.filename}': {suffix or 'no suffix'} not allowed",
            field="files",
            detail={"allowed": sorted(ALLOWED_SUFFIXES)},
        )
    limit = get_settings().max_upload_mb * 1024 * 1024
    if len(f.data) > limit:
        raise MRFError(
            MRFCode.INPUT_FILE_SIZE, f"'{f.filename}' exceeds {get_settings().max_upload_mb} MB", field="files"
        )


async def create_pipeline(
    *,
    model_name: str,
    files: list[UploadedFile] | None = None,
    source_refs: list[ArtifactRef] | None = None,
    owner: str | None = None,
    description: str | None = None,
    dataset_ids: list[str] | None = None,
) -> tuple[Pipeline, ModelRecord]:
    """Store sources, create ModelRecord + Pipeline(received). Caller submits the 'pipeline' job."""
    repo, blobs = get_repo(), get_blobs()
    if not files and not source_refs:
        raise MRFError(MRFCode.INPUT_BODY, "at least one source file is required", field="files")
    model_id, pipeline_id = new_id("model"), new_id("pipeline")
    refs = list(source_refs or [])
    for f in files or []:
        _check_file(f)
        name = PurePosixPath(f.filename.replace("\\", "/")).name
        media = f.media_type or mimetypes.guess_type(name)[0] or "text/plain"
        refs.append(await blobs.put_bytes(f"models/{model_id}/source/{name}", f.data, media_type=media, filename=name))
    model = ModelRecord(
        model_id=model_id,
        name=model_name,
        owner=owner,
        description=description,
        source_files=refs,
        pipeline_id=pipeline_id,
    )
    pipeline = Pipeline(pipeline_id=pipeline_id, model_id=model_id, dataset_ids=list(dataset_ids or []))
    pipeline.history.append(_first_transition())
    await repo.put(Collections.MODELS, model_id, model)
    await repo.put(Collections.PIPELINES, pipeline_id, pipeline)
    return pipeline, model


def _first_transition() -> Any:
    from mrf.contracts.models import StateTransition

    return StateTransition(from_state=None, to_state=PipelineState.RECEIVED, actor="api")


async def decide_review(review_id: str, decision: ReviewDecision, operator: str) -> tuple[Review, Job]:
    """Record a human decision and enqueue the resume job (POST /reviews/{id}/decision)."""
    from mrf.jobs import get_executor

    repo = get_repo()
    review = await repo.get(Collections.REVIEWS, review_id, Review)
    version = await repo.get_version(Collections.REVIEWS, review_id)
    if review.status != "pending":
        raise MRFError(MRFCode.INVALID_STATE, f"review already {review.status}")
    pipeline = await repo.get(Collections.PIPELINES, review.pipeline_id, Pipeline)
    expected = {
        Gate.H1: PipelineState.AWAITING_DOC_APPROVAL,
        Gate.H2: PipelineState.AWAITING_SIGNOFF,
        Gate.MANUAL: PipelineState.MANUAL_REVIEW,
    }[review.gate]
    if pipeline.state != expected:
        raise MRFError(MRFCode.INVALID_STATE, f"pipeline is {pipeline.state.value}, expected {expected.value}")
    if review.gate == Gate.H2 and decision.decision == "edit":
        raise MRFError(MRFCode.INPUT_BODY, "H2 sign-off supports approve or reject only", field="decision")
    if decision.target_state is not None:
        if review.gate != Gate.MANUAL:
            raise MRFError(MRFCode.INPUT_BODY, "target_state is only valid for manual reviews", field="target_state")
        if decision.target_state not in TARGET_NODES:
            raise MRFError(
                MRFCode.INPUT_BODY,
                f"cannot resume at {decision.target_state.value}",
                field="target_state",
                detail={"allowed": [s.value for s in TARGET_NODES]},
            )
    review.status = {"approve": "approved", "reject": "rejected", "edit": "edited"}[decision.decision]  # type: ignore[assignment]
    review.decided_by, review.decided_at = operator, utcnow()
    review.comment, review.edits = decision.comment, decision.edits
    await repo.put(Collections.REVIEWS, review_id, review, if_version=version)  # two reviewers -> one wins
    payload = {"decision": decision.model_dump(mode="json") | {"operator": operator}, "review_id": review_id}
    job, _ = await get_executor().submit("pipeline_resume", {"pipeline_id": review.pipeline_id}, payload=payload)
    return review, job


async def trigger_revalidation(model_id: str, reason: str) -> Job:
    """For A4 monitoring: drift above threshold -> back to usability_run (MRF-3201 if not in monitoring)."""
    from mrf.jobs import get_executor

    repo = get_repo()
    model = await repo.get(Collections.MODELS, model_id, ModelRecord)
    if not model.pipeline_id:
        raise MRFError(MRFCode.INVALID_STATE, "model has no pipeline")
    pipeline = await repo.get(Collections.PIPELINES, model.pipeline_id, Pipeline)
    if pipeline.state != PipelineState.MONITORING:
        raise MRFError(MRFCode.INVALID_STATE, f"pipeline is {pipeline.state.value}, expected monitoring")
    job, _ = await get_executor().submit(
        "pipeline_reenter",
        {"pipeline_id": pipeline.pipeline_id},
        payload={"node": "usability_run", "feedback": [reason]},
    )
    return job


# ---------------------------------------------------------------------- orchestrator singleton
_orchestrator: Orchestrator | None = None
_conn: Any = None


async def get_orchestrator() -> Orchestrator:
    global _orchestrator, _conn
    if _orchestrator is None:
        settings = get_settings()
        saver: BaseCheckpointSaver[Any]
        if settings.storage_backend == "memory":
            saver = InMemorySaver()
        else:
            import aiosqlite
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            settings.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            _conn = await aiosqlite.connect(str(settings.checkpoint_path))
            saver = AsyncSqliteSaver(_conn)
        _orchestrator = Orchestrator(checkpointer=saver)
    return _orchestrator


def set_orchestrator(orchestrator: Orchestrator | None) -> None:
    global _orchestrator
    _orchestrator = orchestrator


async def close_orchestrator() -> None:
    global _orchestrator, _conn
    if _conn is not None:
        await _conn.close()
    _orchestrator, _conn = None, None
