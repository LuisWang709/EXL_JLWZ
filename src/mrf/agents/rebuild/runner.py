"""Model runner - implements ``ModelRunner`` (registry slot ``runner``).

Scores a registered dataset with the model's parity-proven Python rebuild (in the sandbox) and measures it with
``mrf.validation``:

1. data-quality gate (usability runs): a dataset that fails its checks is refused (MRF-3101);
2. the latest rebuild that passed parity provides the code - no proven rebuild, no run (MRF-3201);
3. scores are written to ``runs/<model>/<run>/scores.csv`` (record id + ``score``) for reports and monitoring;
4. metrics: discrimination and calibration when the target is present, score PSI against a reference
   (the baseline run for monitoring batches, the development dataset for other usability runs), fairness by the
   configured segment column;
5. parameters and metrics are logged to MLflow when it is installed (``Run.mlflow_run_id``).
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Literal

from mrf.agents.rebuild.execution import ScoringError, score_csv
from mrf.config import get_policy, get_settings
from mrf.contracts.agents import StepContext
from mrf.contracts.models import Dataset, Rebuild, Run
from mrf.core import MRFCode, MRFError
from mrf.core.ids import new_id
from mrf.storage import Collections, get_blobs, get_repo

log = logging.getLogger(__name__)
DEFAULT_TARGET = "default_flag"


async def proven_rebuild(model_id: str, rebuild_id: str | None = None) -> Rebuild:
    """The rebuild to score with: the given one, else the newest that passed parity and has code."""
    repo = get_repo()
    if rebuild_id:
        rb = await repo.get_or_none(Collections.REBUILDS, rebuild_id, Rebuild)
        if rb and rb.status == "passed" and rb.code and rb.parity and not rb.parity.detail.get("skipped"):
            return rb
    found = (await repo.find(Collections.REBUILDS, Rebuild, where={"model_id": model_id}, page_size=100)).items
    usable = [r for r in found if r.status == "passed" and r.code and r.parity and not r.parity.detail.get("skipped")]
    if not usable:
        raise MRFError(
            MRFCode.INVALID_STATE,
            "the model has no Python rebuild that passed parity; nothing to run",
            detail={"model_id": model_id},
        )
    return max(usable, key=lambda r: r.created_at)


def _is_binary(series: Any) -> bool:
    values = set(series.dropna().unique().tolist())
    return len(values) == 2 and values <= {0, 1}


def _metrics(frame: Any, scores: Any, target: str | None, link: str, segment: str | None) -> dict[str, Any]:
    import numpy as np

    from mrf import validation as v

    out: dict[str, Any] = {
        "n_records": len(frame),
        "score_mean": float(np.nanmean(scores)),
        "n_missing_scores": int(np.isnan(scores).sum()),
    }
    if target is None or target not in frame.columns:
        return out
    y = frame[target]
    mask = ~np.isnan(scores) & y.notna().to_numpy()
    y, s = y[mask], scores[mask]
    if link == "logit" and _is_binary(y):
        out["observed_rate"] = float(y.mean())
        out["auc"] = float(v.auc(y, s))
        out["gini"] = float(v.gini(y, s))
        out["ks"] = float(v.ks(y, s))
        out["brier"] = float(v.brier(y, s))
        try:
            out["hosmer_lemeshow"] = v.hosmer_lemeshow(y, s)
        except MRFError as exc:  # too few records per group etc.: the metric is simply absent
            log.info("runner: hosmer-lemeshow skipped: %s", exc.message)
        if segment and segment in frame.columns:
            try:
                out["fairness"] = v.fairness(y, s, frame[segment][mask])
            except MRFError as exc:
                log.info("runner: fairness skipped: %s", exc.message)
    else:
        err = s - y.to_numpy(dtype=float)
        total = float(((y - y.mean()) ** 2).sum())
        out["rmse"] = float(np.sqrt((err**2).mean()))
        out["mae"] = float(np.abs(err).mean())
        out["r2"] = float(1 - (err**2).sum() / total) if total > 0 else None
    return out


def _log_mlflow(name: str, params: dict[str, Any], metrics: dict[str, Any]) -> str | None:
    """Best effort: MLflow is optional (extra ``mlops``); a logging failure never fails the run."""
    try:
        import mlflow
    except ImportError:
        return None
    try:
        root = Path(get_settings().data_dir).resolve() / "mlruns"
        mlflow.set_tracking_uri(root.as_uri())
        mlflow.set_experiment("model-risk-factory")
        with mlflow.start_run(run_name=name) as active:
            mlflow.log_params({k: str(v)[:250] for k, v in params.items()})
            mlflow.log_metrics({k: float(v) for k, v in metrics.items() if isinstance(v, int | float) and v == v})
            return str(active.info.run_id)
    except Exception as exc:
        log.warning("runner: mlflow logging failed: %s", exc)
        return None


class ModelRunnerImpl:
    async def run(self, ctx: StepContext, dataset_id: str, kind: str = "usability") -> Run:
        from mrf.monitoring.frames import load_frame, run_scores

        started = time.monotonic()
        repo = get_repo()
        dataset = await repo.get(Collections.DATASETS, dataset_id, Dataset)
        run_kind: Literal["usability", "batch"] = "batch" if kind == "batch" else "usability"

        if run_kind == "usability":  # monitoring checks its batches itself before calling the runner
            from mrf.monitoring.quality import QualityCheckerImpl

            quality = await QualityCheckerImpl().check(dataset_id)
            if not quality.passed:
                failed = [c.name for c in quality.checks if not c.passed and c.severity == "red"]
                raise MRFError(
                    MRFCode.DATA_QUALITY_FAILED,
                    f"dataset {dataset_id} failed quality checks: {', '.join(failed) or 'see detail'}",
                    detail={"dataset_id": dataset_id, "failed_checks": failed},
                )

        rebuild = await proven_rebuild(ctx.model.model_id, ctx.artifacts.get("rebuild_id"))
        assert rebuild.code is not None and rebuild.parity is not None  # noqa: S101 - proven_rebuild guarantees it
        code = (await get_blobs().get_bytes(rebuild.code.uri)).decode("utf-8")
        link = str((rebuild.parity.detail.get("spec") or {}).get("link") or "logit")

        frame = await asyncio.to_thread(load_frame, dataset)
        scores = await self._score(code, frame, dataset_id)

        import numpy as np
        import pandas as pd

        run_id = new_id("run")
        id_column = next((c.name for c in dataset.columns if c.role == "id"), None) or ("id" if "id" in frame else None)
        out = pd.DataFrame({"score": scores})
        if id_column and id_column in frame.columns:
            out.insert(0, id_column, frame[id_column].to_numpy())
        ref = await get_blobs().put_bytes(
            f"runs/{ctx.model.model_id}/{run_id}/scores.csv",
            out.to_csv(index=False).encode("utf-8"),
            media_type="text/csv",
            filename="scores.csv",
        )

        policy = get_policy()
        segment = str((policy.get("reporting") or {}).get("fairness_segment_column") or "") or None
        target = next((c.name for c in dataset.columns if c.role == "target"), None)
        if target is None:
            declared = ctx.model.classification.target if ctx.model.classification else None
            target = next((t for t in (declared, DEFAULT_TARGET) if t and t in frame.columns), None)
        metrics = await asyncio.to_thread(_metrics, frame, np.asarray(scores, dtype=float), target, link, segment)

        # score stability against a reference population
        reference: Any = None
        reference_source = None
        baseline_run_id = ctx.artifacts.get("baseline_run_id")
        if baseline_run_id:
            baseline_run = await repo.get_or_none(Collections.RUNS, str(baseline_run_id), Run)
            reference = await asyncio.to_thread(run_scores, baseline_run)
            reference_source = f"run:{baseline_run_id}"
        if reference is None:
            ref_id = ctx.artifacts.get("reference_dataset_id") or await self._development_dataset(ctx, dataset)
            if ref_id and ref_id != dataset_id:
                ref_ds = await repo.get_or_none(Collections.DATASETS, str(ref_id), Dataset)
                if ref_ds is not None:
                    ref_frame = await asyncio.to_thread(load_frame, ref_ds)
                    reference = np.asarray(await self._score(code, ref_frame, str(ref_id)), dtype=float)
                    reference_source = f"dataset:{ref_id}"
        if reference is not None:
            from mrf import validation as v

            try:
                metrics["psi_score"] = float(await asyncio.to_thread(v.psi, reference, np.asarray(scores, dtype=float)))
                metrics["psi_reference"] = reference_source
            except MRFError as exc:
                log.info("runner: score PSI skipped: %s", exc.message)

        metrics["duration_ms"] = int((time.monotonic() - started) * 1000)
        metrics["rebuild_id"] = rebuild.rebuild_id
        metrics["dataset_role"] = dataset.role
        mlflow_id = await asyncio.to_thread(
            _log_mlflow,
            f"{ctx.model.name}:{run_kind}:{dataset.name}",
            {
                "model_id": ctx.model.model_id,
                "dataset_id": dataset_id,
                "kind": run_kind,
                "rebuild_id": rebuild.rebuild_id,
                "code_sha256": rebuild.code.sha256,
                "parity_attempts": rebuild.attempt,
            },
            metrics,
        )
        return Run(
            run_id=run_id,
            model_id=ctx.model.model_id,
            dataset_id=dataset_id,
            kind=run_kind,
            status="succeeded",
            metrics=metrics,
            outputs=[ref],
            mlflow_run_id=mlflow_id,
        )

    @staticmethod
    async def _score(code: str, frame: Any, dataset_id: str) -> list[float]:
        try:
            scores = await score_csv(code, frame.to_csv(index=False))
        except ScoringError as exc:
            raise MRFError(
                MRFCode.INVALID_STATE,
                f"the rebuilt model could not score dataset {dataset_id}: {exc}",
                detail={"dataset_id": dataset_id},
            ) from exc
        if len(scores) != len(frame):
            raise MRFError(
                MRFCode.INVALID_STATE,
                f"the rebuilt model returned {len(scores)} scores for {len(frame)} records",
                detail={"dataset_id": dataset_id},
            )
        return scores

    @staticmethod
    async def _development_dataset(ctx: StepContext, current: Dataset) -> str | None:
        if current.role == "development":
            return None
        repo = get_repo()
        for ds_id in ctx.dataset_ids:
            ds = await repo.get_or_none(Collections.DATASETS, ds_id, Dataset)
            if ds is not None and ds.role == "development":
                return ds.dataset_id
        return None
