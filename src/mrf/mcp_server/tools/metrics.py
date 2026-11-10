"""Owner: A3 (implemented on top of mrf.validation)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from mrf.core import MRFCode, MRFError

if TYPE_CHECKING:
    import pandas as pd

SUPPORTED = ("auc", "gini", "ks", "brier", "hosmer_lemeshow", "psi", "csi", "fairness")
_NEEDS_TARGET = {"auc", "gini", "ks", "brier", "hosmer_lemeshow", "fairness"}
_NEEDS_PROB = {"brier", "hosmer_lemeshow"}
_NEEDS_REFERENCE = {"psi", "csi"}
#: never treated as model features when computing CSI
_NON_FEATURES = {"id", "default_flag", "target", "label", "y"}


async def compute_metrics(
    dataset_id: str,
    score_column: str,
    target_column: str | None = None,
    metrics: list[str] | None = None,
    reference_dataset_id: str | None = None,
    segment_column: str | None = None,
) -> dict[str, Any]:
    """Compute validation metrics. Supported names: auc, gini, ks, brier, hosmer_lemeshow,
    psi, csi, fairness (needs segment_column). Default: all applicable.

    Returns {"metrics": {name: value | dict}, "n_records": int, "warnings": [str]}.
    psi/csi need ``reference_dataset_id``.
    """
    unknown = sorted(set(metrics or []) - set(SUPPORTED))
    if unknown:
        raise MRFError(MRFCode.INPUT_BODY, f"unknown metrics {unknown}; supported: {list(SUPPORTED)}", field="metrics")
    frame = await _load(dataset_id)
    reference = await _load(reference_dataset_id) if reference_dataset_id else None
    return await asyncio.to_thread(
        _compute, frame, reference, score_column, target_column, metrics, segment_column, dataset_id
    )


async def _load(dataset_id: str) -> pd.DataFrame:
    from mrf.contracts.models import Dataset
    from mrf.monitoring.frames import load_frame
    from mrf.storage import Collections, get_repo

    ds = await get_repo().get(Collections.DATASETS, dataset_id, Dataset)  # unknown -> MRF-1404
    try:
        return await asyncio.to_thread(load_frame, ds)
    except (OSError, ValueError, ImportError, NotImplementedError) as exc:
        raise MRFError(MRFCode.INPUT_DATA_SCHEMA, f"dataset {dataset_id} could not be read: {exc}") from exc


def _require(df: pd.DataFrame, column: str | None, field: str, dataset_id: str) -> None:
    if column is not None and column not in df.columns:
        raise MRFError(
            MRFCode.INPUT_DATA_SCHEMA,
            f"column '{column}' not in dataset {dataset_id} (columns: {list(df.columns)[:30]})",
            field=field,
        )


def _compute(
    df: pd.DataFrame,
    ref: pd.DataFrame | None,
    score_column: str,
    target_column: str | None,
    requested: list[str] | None,
    segment_column: str | None,
    dataset_id: str,
) -> dict[str, Any]:
    import pandas as pd

    from mrf import validation as v

    _require(df, score_column, "score_column", dataset_id)
    _require(df, target_column, "target_column", dataset_id)
    _require(df, segment_column, "segment_column", dataset_id)
    warnings: list[str] = []
    score = pd.to_numeric(df[score_column], errors="coerce")
    if score.isna().all():
        raise MRFError(MRFCode.INPUT_DATA_SCHEMA, f"score column '{score_column}' has no numeric values")
    in_unit = bool(score.dropna().between(0, 1).all())

    names = list(requested) if requested else list(SUPPORTED)
    explicit = requested is not None
    plan: list[str] = []
    for name in names:
        reason = None
        if name in _NEEDS_TARGET and target_column is None:
            reason = "needs target_column"
        elif name in _NEEDS_PROB and not in_unit:
            reason = f"needs probabilities in [0, 1]; '{score_column}' is outside that range"
        elif name in _NEEDS_REFERENCE and ref is None:
            reason = "needs reference_dataset_id"
        elif name == "fairness" and segment_column is None:
            reason = "needs segment_column"
        if reason is None:
            plan.append(name)
        elif explicit:
            warnings.append(f"{name} skipped: {reason}")

    out: dict[str, Any] = {}
    y = pd.to_numeric(df[target_column], errors="coerce") if target_column else None
    if y is not None:
        dropped = int((y.isna() | score.isna()).sum())
        if dropped:
            warnings.append(f"{dropped} rows with a missing score or target were excluded")
    for name in plan:
        try:
            if name in {"auc", "gini", "ks", "brier"}:
                out[name] = getattr(v, name)(y, score)
            elif name == "hosmer_lemeshow":
                out[name] = v.hosmer_lemeshow(y, score)
            elif name == "fairness" and segment_column is not None:
                out[name] = v.fairness(y, score, df[segment_column])
            elif name == "psi" and ref is not None:
                _require(ref, score_column, "score_column", "reference")
                out[name] = v.psi(pd.to_numeric(ref[score_column], errors="coerce"), score)
            elif name == "csi" and ref is not None:
                skip = {score_column, target_column, *_NON_FEATURES}  # a segment (age_band) can be a feature
                features = [c for c in df.columns if c in ref.columns and c not in skip]
                out[name] = v.csi(ref[features], df[features], columns=features)
        except MRFError as exc:
            if explicit and len(plan) == 1:
                raise
            warnings.append(f"{name} not computed: {exc.message}")
    if "auc" in out and out["auc"] < 0.5:
        warnings.append(
            f"AUC {out['auc']:.3f} < 0.5: '{score_column}' looks reverse-oriented (higher = safer); negate it"
        )
    return {"metrics": out, "n_records": len(df), "warnings": warnings}
