"""Owner: A3 (implemented on top of mrf.validation)."""

from __future__ import annotations

from typing import Any


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
    raise NotImplementedError
