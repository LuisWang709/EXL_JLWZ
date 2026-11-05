"""Shared domain models - the Python side of openapi.yaml ``components.schemas``.

Frozen together with API contract v1. Adding *optional* fields is allowed (tell A1);
renaming/removing fields needs /api/v2.

Datasets are not fixed yet, so data-related models are deliberately permissive:
formats include an ``other`` bucket, column dtypes are free strings, and every
entity carries a ``metadata`` dict for anything we did not anticipate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from mrf.core.states import PipelineState


def utcnow() -> datetime:
    return datetime.now(UTC)


class _Base(BaseModel):
    model_config = ConfigDict(use_enum_values=False, populate_by_name=True)


# ------------------------------------------------------------------ common
class ArtifactRef(_Base):
    """A file we stored: local path (``file://``) or blob (``https://...``)."""

    uri: str
    filename: str
    media_type: str = "application/octet-stream"
    sha256: str | None = None
    size_bytes: int | None = None


class Evidence(_Base):
    """Every claim in a document / classification must point to one of these."""

    source: Literal["code", "data", "kb", "tool", "human"]
    ref: str = Field(description="e.g. 'm001_scorecard.sas:12-20', 'kb:ss1-23#p4.2', 'tool:profile_data#call_3'")
    quote: str | None = None


class Usage(_Base):
    """LLM/tool cost accounting, aggregated per step for evaluation (docs/evaluation.md)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_eur: float = 0.0
    latency_ms: int = 0
    llm_calls: int = 0
    backoff_retries: int = 0


# ------------------------------------------------------------------ inventory / identification
class ModelLanguage(str, Enum):
    SAS = "sas"
    R = "r"
    PYTHON = "python"
    OTHER = "other"
    UNKNOWN = "unknown"


class ClassificationResult(_Base):
    language: ModelLanguage
    algorithm: str = Field(
        description="free text, suggested: logistic_regression, linear_regression, decision_tree, "
        "gradient_boosting, scorecard, other"
    )
    purpose: str = Field(description="free text, suggested: pd, lgd, ead, pricing, behavioural_score, fraud, other")
    target: str | None = None
    features: list[str] = Field(default_factory=list)
    procedures: list[str] = Field(default_factory=list, description="e.g. ['PROC LOGISTIC'], ['glm(binomial)']")
    confidence: float = Field(ge=0.0, le=1.0)
    needs_review: bool = False
    evidence: list[Evidence] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelRecord(_Base):
    """Model inventory entry (清单记录)."""

    model_id: str
    name: str
    owner: str | None = None
    description: str | None = None
    source_files: list[ArtifactRef] = Field(default_factory=list)
    classification: ClassificationResult | None = None
    pipeline_id: str | None = None
    lifecycle: Literal["registered", "documented", "rebuilt", "validated", "production", "retired"] = "registered"
    tags: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ------------------------------------------------------------------ data
class DatasetFormat(str, Enum):
    CSV = "csv"
    TSV = "tsv"
    PARQUET = "parquet"
    FEATHER = "feather"
    XLSX = "xlsx"
    XLS = "xls"
    JSON = "json"
    JSONL = "jsonl"
    SAS7BDAT = "sas7bdat"
    XPT = "xpt"
    RDS = "rds"
    RDATA = "rdata"
    SQL = "sql"  # a query / table reference
    OTHER = "other"


class ColumnInfo(_Base):
    name: str
    dtype: str = Field(description="free string: 'int64', 'float', 'category', 'date', 'string', 'NUM', 'CHAR'...")
    role: Literal["feature", "target", "id", "weight", "date", "segment", "score", "other"] = "feature"
    nullable: bool = True
    description: str | None = None


class Dataset(_Base):
    dataset_id: str
    name: str
    uri: str = Field(description="blob url, file path, or connection string reference (never a secret)")
    format: DatasetFormat = DatasetFormat.OTHER
    role: Literal["development", "out_of_time", "validation", "monitoring_batch", "reference", "other"] = "other"
    model_id: str | None = None
    schema_name: str | None = Field(default=None, description="pandera schema registered in mrf.data.schemas")
    columns: list[ColumnInfo] = Field(default_factory=list)
    row_count: int | None = None
    read_options: dict[str, Any] = Field(
        default_factory=dict, description="passed to the reader, e.g. sep, encoding, sheet"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class QualityCheck(_Base):
    name: str
    passed: bool
    severity: Literal["info", "amber", "red"] = "info"
    value: float | str | None = None
    threshold: float | str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class QualityReport(_Base):
    dataset_id: str
    passed: bool
    checks: list[QualityCheck] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


# ------------------------------------------------------------------ documentation & rating
class Document(_Base):
    doc_id: str
    model_id: str
    attempt: int = 1
    content_md: str = ""
    sections: dict[str, str] = Field(default_factory=dict, description="SS1/23 section id -> markdown")
    evidence: list[Evidence] = Field(default_factory=list)
    status: Literal["draft", "rated", "approved", "rejected"] = "draft"
    usage: Usage = Field(default_factory=Usage)
    created_at: datetime = Field(default_factory=utcnow)


class Rating(_Base):
    rating_id: str
    doc_id: str
    attempt: int
    rule_score: float = Field(ge=0, le=60)
    llm_score: float = Field(ge=0, le=40)
    total: float = Field(ge=0, le=100)
    passed: bool
    veto_flags: list[str] = Field(default_factory=list)
    comments: list[str] = Field(default_factory=list, description="fed back into the next draft")
    breakdown: dict[str, float] = Field(default_factory=dict)
    usage: Usage = Field(default_factory=Usage)
    created_at: datetime = Field(default_factory=utcnow)


# ------------------------------------------------------------------ rebuild & parity
class ParityResult(_Base):
    passed: bool
    n_records: int = 0
    n_mismatches: int = 0
    max_abs_diff: float | None = None
    tolerance: float | None = None
    mismatch_examples: list[dict[str, Any]] = Field(default_factory=list)
    detail: dict[str, Any] = Field(default_factory=dict)


class Rebuild(_Base):
    rebuild_id: str
    model_id: str
    attempt: int = 1
    target_language: Literal["python"] = "python"
    code: ArtifactRef | None = None
    parity: ParityResult | None = None
    certificate: ArtifactRef | None = None
    feedback: list[str] = Field(default_factory=list)
    status: Literal["generating", "testing", "passed", "failed"] = "generating"
    usage: Usage = Field(default_factory=Usage)
    created_at: datetime = Field(default_factory=utcnow)


# ------------------------------------------------------------------ runs, reports
class Run(_Base):
    run_id: str
    model_id: str
    dataset_id: str
    kind: Literal["usability", "batch"] = "usability"
    status: Literal["queued", "running", "succeeded", "failed"] = "queued"
    metrics: dict[str, Any] = Field(default_factory=dict)
    outputs: list[ArtifactRef] = Field(default_factory=list)
    mlflow_run_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Report(_Base):
    report_id: str
    model_id: str
    type: Literal["analysis", "validation", "monitoring", "parity_certificate"]
    artifact: ArtifactRef | None = None
    rag_status: Literal["green", "amber", "red"] | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


# ------------------------------------------------------------------ human review
class Gate(str, Enum):
    H1 = "H1"  # documentation approval
    H2 = "H2"  # validation sign-off
    MANUAL = "manual"  # retries exhausted / low confidence / rejected


class Review(_Base):
    review_id: str
    pipeline_id: str
    model_id: str
    gate: Gate
    reason: str
    reason_code: str | None = Field(default=None, description="MRF code that caused it, for MANUAL")
    status: Literal["pending", "approved", "rejected", "edited"] = "pending"
    payload: dict[str, Any] = Field(
        default_factory=dict, description="what the reviewer sees: doc_id, rating, report ids..."
    )
    decided_by: str | None = None
    decided_at: datetime | None = None
    comment: str | None = None
    edits: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class ReviewDecision(_Base):
    decision: Literal["approve", "reject", "edit"]
    comment: str | None = None
    edits: dict[str, Any] = Field(default_factory=dict)
    target_state: PipelineState | None = Field(
        default=None, description="MANUAL gate only: where to resume (defaults to the step that failed)"
    )


# ------------------------------------------------------------------ jobs & pipelines
class Job(_Base):
    job_id: str
    kind: str = Field(
        description="handler name: pipeline, pipeline_resume, pipeline_reenter, document, rebuild, run ..."
    )
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"] = "queued"
    resource: dict[str, str] = Field(default_factory=dict, description="e.g. {'pipeline_id': 'pl_..'}")
    payload: dict[str, Any] = Field(default_factory=dict, description="handler input (request body, decision...)")
    progress: float = 0.0
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    idempotency_key: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class StateTransition(_Base):
    from_state: PipelineState | None
    to_state: PipelineState
    at: datetime = Field(default_factory=utcnow)
    actor: str = "system"
    note: str | None = None
    code: str | None = None


class Pipeline(_Base):
    pipeline_id: str
    model_id: str
    state: PipelineState = PipelineState.RECEIVED
    current_step: str | None = None
    attempts: dict[str, int] = Field(default_factory=dict, description="{'doc': 2, 'parity': 1, ...}")
    dataset_ids: list[str] = Field(default_factory=list)
    history: list[StateTransition] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    last_error: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ------------------------------------------------------------------ monitoring
class MonitoringMetric(_Base):
    model_id: str
    batch_id: str
    at: datetime = Field(default_factory=utcnow)
    row_count: int | None = None
    missing_rate: dict[str, float] = Field(default_factory=dict)
    psi: dict[str, float] = Field(default_factory=dict, description="feature -> PSI; key '__score__' for score PSI")
    gini: float | None = None
    status: Literal["green", "amber", "red"] = "green"


class Alert(_Base):
    alert_id: str
    model_id: str
    severity: Literal["amber", "red"]
    kind: Literal["drift", "data_quality", "performance", "system", "queue_sla"]
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)
    acknowledged: bool = False
    created_at: datetime = Field(default_factory=utcnow)


ReportKind = Literal["monitoring", "validation"]


def _default_report_types() -> list[ReportKind]:
    return ["monitoring"]


class Schedule(_Base):
    model_id: str
    cron: str
    enabled: bool = True
    report_types: list[ReportKind] = Field(default_factory=_default_report_types)
