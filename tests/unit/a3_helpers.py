"""Shared setup for A3 tests: the M001 SAS fixture registered as a classified model."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from mrf.agents.classify.agent import ClassifierAgent
from mrf.contracts.agents import StepContext
from mrf.contracts.models import ColumnInfo, Dataset, Document, Evidence, ModelRecord
from mrf.storage import Collections, get_blobs, get_repo

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SAS = FIXTURES / "classify" / "m001_pd_scorecard.sas"


async def m001_context(
    dataset_ids: list[str] | None = None, feedback: list[str] | None = None, attempt: int = 1
) -> StepContext:
    ref = await get_blobs().put_bytes(
        "models/mdl_m001/source/m001_pd_scorecard.sas", SAS.read_bytes(), media_type="text/plain", filename=SAS.name
    )
    model = ModelRecord(model_id="mdl_m001", name="M001 Retail PD scorecard", source_files=[ref])
    ctx = StepContext(pipeline_id="pl_m001", model=model, source_files=[ref], dataset_ids=dataset_ids or [])
    model.classification = await ClassifierAgent().classify(ctx)
    await get_repo().put(Collections.MODELS, model.model_id, model)
    return ctx.model_copy(update={"model": model, "feedback": feedback or [], "attempt": attempt})


async def scored_m001_dataset(tmp_path: Path) -> Dataset:
    """Fixture rows joined with the legacy scores, registered with score / target roles."""
    data = pd.read_csv(FIXTURES / "m001" / "input_sample.csv")
    scores = pd.read_csv(FIXTURES / "m001" / "legacy_scores.csv")[["id", "pd_legacy"]]
    path = tmp_path / "m001_scored.csv"
    data.merge(scores, on="id").to_csv(path, index=False)
    ds = Dataset(
        dataset_id="ds_m001_scored",
        name="M001 scored sample",
        uri=str(path),
        role="validation",
        model_id="mdl_m001",
        columns=[
            ColumnInfo(name="pd_legacy", dtype="float", role="score"),
            ColumnInfo(name="default_flag", dtype="int", role="target"),
            ColumnInfo(name="age_band", dtype="int", role="segment"),
        ],
    )
    await get_repo().put(Collections.DATASETS, ds.dataset_id, ds)
    return ds


def broken_copy(doc: Document, **changes: object) -> Document:
    """A deliberately bad variant of a good document (rater calibration)."""
    return doc.model_copy(update={"doc_id": f"{doc.doc_id}_bad", **changes}, deep=True)


def with_evidence(doc: Document, evidence: list[Evidence]) -> Document:
    return doc.model_copy(update={"evidence": evidence}, deep=True)
