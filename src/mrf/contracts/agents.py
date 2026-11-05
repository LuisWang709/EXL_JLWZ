"""Interfaces between the orchestrator (A1) and the modules owned by A2/A3/A4.

The orchestrator only depends on these Protocols. Each owner provides a concrete class and
registers it in ``mrf.orchestrator.registry`` (A1). Until then the orchestrator uses stubs,
so everyone can develop in parallel after the contract freeze.

Rules for every implementation:
  * async, no global state; all external data comes through MCP tools (ToolGateway);
  * raise :class:`mrf.core.MRFError` with an MRF code on failure - never return ``None``;
  * report LLM/tool cost in the returned object's ``usage`` field;
  * do NOT retry quality failures yourself - the orchestrator owns retry counting.
    (Transient LLM retries are already handled inside mrf.llm.)
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from mrf.contracts.models import (
    ArtifactRef,
    ClassificationResult,
    Document,
    ModelRecord,
    QualityReport,
    Rating,
    Rebuild,
    Report,
    Run,
)


class StepContext(BaseModel):
    """What the orchestrator passes into every step."""

    pipeline_id: str
    model: ModelRecord
    source_files: list[ArtifactRef] = Field(default_factory=list)
    dataset_ids: list[str] = Field(default_factory=list)
    attempt: int = 1
    feedback: list[str] = Field(
        default_factory=list, description="reviewer / rater / parity feedback from the previous attempt"
    )
    artifacts: dict[str, Any] = Field(
        default_factory=dict, description="ids produced by earlier steps: doc_id, rebuild_id ..."
    )


# ---------------------------------------------------------------- A1
@runtime_checkable
class Classifier(Protocol):
    async def classify(self, ctx: StepContext) -> ClassificationResult: ...


# ---------------------------------------------------------------- A3
@runtime_checkable
class DocWriter(Protocol):
    async def draft(self, ctx: StepContext) -> Document: ...


@runtime_checkable
class Rater(Protocol):
    async def rate(self, ctx: StepContext, document: Document) -> Rating: ...


@runtime_checkable
class ReportBuilder(Protocol):
    async def build(self, ctx: StepContext, report_type: str) -> Report: ...


# ---------------------------------------------------------------- A2
@runtime_checkable
class Rebuilder(Protocol):
    async def rebuild(self, ctx: StepContext) -> Rebuild:
        """Generate python code AND run parity; ``Rebuild.parity.passed`` drives the loop."""
        ...


@runtime_checkable
class ModelRunner(Protocol):
    async def run(self, ctx: StepContext, dataset_id: str, kind: str = "usability") -> Run: ...


# ---------------------------------------------------------------- A4
@runtime_checkable
class DataQualityChecker(Protocol):
    async def check(self, dataset_id: str) -> QualityReport: ...


@runtime_checkable
class MonitoringRegistrar(Protocol):
    async def register(self, ctx: StepContext, cron: str | None = None) -> None: ...
