"""Shared fakes for the A4 monitoring tests: A3's psi/csi, A2's runner, A1's trigger_revalidation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from mrf.contracts.agents import StepContext
from mrf.contracts.models import Dataset, Job, ModelRecord, Run
from mrf.core import MRFCode, MRFError
from mrf.core.ids import new_id
from mrf.monitoring import batch, drift
from mrf.monitoring.registrar import TAG_BASELINE_DATASET
from mrf.storage import Collections, get_repo


def fake_csi(expected: pd.DataFrame, actual: pd.DataFrame, columns: list[str] | None = None) -> dict[str, float]:
    """Stand-in for mrf.validation.csi: |mean shift| per column, easy to steer from a test."""
    return {c: abs(float(actual[c].mean()) - float(expected[c].mean())) for c in (columns or list(actual.columns))}


def fake_psi(expected: pd.Series, actual: pd.Series, **_: Any) -> float:
    return abs(float(actual.mean()) - float(expected.mean()))


def use_fake_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drift, "_validation", lambda: (fake_psi, fake_csi))


class FakeRunner:
    def __init__(self, gini: float | None = None) -> None:
        self.gini = gini
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def run(self, ctx: StepContext, dataset_id: str, kind: str = "usability") -> Run:
        self.calls.append((dataset_id, kind, dict(ctx.artifacts)))
        metrics = {} if self.gini is None else {"gini": self.gini}
        return Run(
            run_id=new_id("run"),
            model_id=ctx.model.model_id,
            dataset_id=dataset_id,
            kind="batch",
            status="succeeded",
            metrics=metrics,
        )


class RevalidationSpy:
    def __init__(self, already_running: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self.already_running = already_running

    async def __call__(self, model_id: str, reason: str, dataset_id: str | None = None) -> Job:
        self.calls.append((model_id, reason))
        if self.already_running:
            raise MRFError(MRFCode.INVALID_STATE, "pipeline is usability_run, expected monitoring")
        return Job(job_id="job_reval", kind="pipeline_reenter")


def install(monkeypatch: pytest.MonkeyPatch, runner: FakeRunner, spy: RevalidationSpy) -> None:
    from mrf.orchestrator import service

    use_fake_validation(monkeypatch)
    monkeypatch.setattr(batch, "_runner", lambda: runner)
    monkeypatch.setattr(service, "trigger_revalidation", spy)


async def add_dataset(tmp: Path, dataset_id: str, df: pd.DataFrame, **kw: Any) -> Dataset:
    path = tmp / f"{dataset_id}.csv"
    df.to_csv(path, index=False)
    ds = Dataset(dataset_id=dataset_id, name=dataset_id, uri=str(path), **kw)
    await get_repo().put(Collections.DATASETS, dataset_id, ds)
    return ds


async def add_model(model_id: str = "mdl_t", lifecycle: str = "production", baseline: str | None = "ds_base") -> None:
    tags = {TAG_BASELINE_DATASET: baseline} if baseline else {}
    model = ModelRecord(model_id=model_id, name="test model", pipeline_id="pl_t", lifecycle=lifecycle, tags=tags)
    await get_repo().put(Collections.MODELS, model_id, model)


def frame(n: int = 200, shift: float = 0.0, missing: float = 0.0) -> pd.DataFrame:
    """Two numeric features + id + target; ``shift`` moves x1's mean (= the fake CSI)."""
    df = pd.DataFrame(
        {
            "id": range(1, n + 1),
            "x1": [i % 10 / 10 + shift for i in range(n)],
            "x2": [(i * 7) % 5 for i in range(n)],
            "default_flag": [i % 3 == 0 for i in range(n)],
        }
    ).astype({"default_flag": int})
    if missing:
        df.loc[df.index[: int(n * missing)], "x2"] = None
    return df
