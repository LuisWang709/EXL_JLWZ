"""Drift numbers and the green/amber/red verdict. Owner: A4.

PSI/CSI come from A3's ``mrf.validation`` - this module only selects columns, calls those functions and applies
the thresholds in config/pipeline.yaml. Rules (execution plan, monitoring layer):

    max PSI <  psi_amber                         -> green
    psi_amber <= max PSI <= psi_red              -> amber
    max PSI >  psi_red  or  Gini drop > gini_drop_red -> red
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from mrf.config import get_policy
from mrf.contracts.models import Dataset, ModelRecord
from mrf.core import MRFCode, MRFError

if TYPE_CHECKING:
    import pandas as pd

Status = Literal["green", "amber", "red"]
SCORE_KEY = "__score__"
#: fallback exclusions when neither the classifier nor the dataset declares id/target columns
DEFAULT_NON_FEATURES = frozenset({"id", "default_flag", "target", "label", "y"})
_NON_FEATURE_ROLES = frozenset({"id", "target", "weight", "date", "score"})


def thresholds() -> dict[str, Any]:
    policy: dict[str, Any] = get_policy()["monitoring"]
    return policy


def _validation() -> tuple[Callable[..., float], Callable[..., dict[str, float]]]:
    """(psi, csi) from A3's library. Imported lazily so the API starts before A3's module lands."""
    module = importlib.import_module("mrf.validation")
    psi, csi = getattr(module, "psi", None), getattr(module, "csi", None)
    if psi is None or csi is None:
        raise MRFError(MRFCode.INTERNAL, "mrf.validation.psi / csi not available yet (A3)")
    return psi, csi


def pick_features(
    model: ModelRecord, baseline: Dataset, baseline_df: pd.DataFrame, batch_df: pd.DataFrame
) -> list[str]:
    """Columns to compare: the classifier's features if they exist in both frames, else every shared column
    except ids / targets (from Dataset.columns roles, the classifier's target, or DEFAULT_NON_FEATURES)."""
    common = [c for c in batch_df.columns if c in baseline_df.columns]
    cls = model.classification
    if cls and cls.features:
        declared = [f for f in cls.features if f in common]
        if declared:
            return declared
    excluded = {c.name for c in baseline.columns if c.role in _NON_FEATURE_ROLES} | set(DEFAULT_NON_FEATURES)
    if cls and cls.target:
        excluded.add(cls.target)
    return [c for c in common if c not in excluded]


def compute_psi(
    baseline_df: pd.DataFrame,
    batch_df: pd.DataFrame,
    features: list[str],
    baseline_scores: pd.Series | None = None,
    batch_scores: pd.Series | None = None,
) -> dict[str, float]:
    """feature -> CSI, plus ``__score__`` -> PSI when both score series are known."""
    psi, csi = _validation()
    out: dict[str, float] = {}
    if features:
        out.update({k: float(v) for k, v in csi(baseline_df[features], batch_df[features], columns=features).items()})
    if baseline_scores is not None and batch_scores is not None:
        out[SCORE_KEY] = float(psi(baseline_scores, batch_scores))
    return out


def classify(
    psi: dict[str, float],
    gini: float | None = None,
    baseline_gini: float | None = None,
    policy: dict[str, Any] | None = None,
) -> tuple[Status, list[str]]:
    """Verdict + human-readable reasons (the reasons become the alert message and the re-validation feedback)."""
    policy = policy or thresholds()
    amber, red, gini_red = float(policy["psi_amber"]), float(policy["psi_red"]), float(policy["gini_drop_red"])
    reasons: list[str] = []
    status: Status = "green"
    if psi:
        worst_name, worst = max(psi.items(), key=lambda kv: kv[1])
        label = "score" if worst_name == SCORE_KEY else worst_name
        if worst > red:
            status = "red"
            reasons.append(f"PSI {worst:.3f} on {label} > {red}")
        elif worst >= amber:
            status = "amber"
            reasons.append(f"PSI {worst:.3f} on {label} >= {amber}")
    if gini is not None and baseline_gini is not None:
        drop = baseline_gini - gini
        if drop > gini_red:
            status = "red"
            reasons.append(f"Gini fell {drop:.3f} ({baseline_gini:.3f} -> {gini:.3f}) > {gini_red}")
    return status, reasons
