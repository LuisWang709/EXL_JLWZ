"""Validation metric library. Owner: A3.
Single implementation of PSI/CSI - A4 monitoring imports it, never re-implements.

Public API (pure functions on array-likes; signatures frozen with contract v1):

    auc(y_true, score) -> float
    gini(y_true, score) -> float                      # 2*AUC - 1
    ks(y_true, score) -> float
    brier(y_true, prob) -> float
    hosmer_lemeshow(y_true, prob, groups=10) -> dict  # {"statistic", "p_value", "df", "groups", "table"}
    psi(expected, actual, bins=10, binning="quantile") -> float
    csi(expected_df, actual_df, columns=None, bins=10) -> dict[str, float]
    fairness(y_true, score, segment, threshold=None) -> dict  # per-segment rates, disparate impact

Implemented in mrf.validation.metrics (needs the ``data`` extra: numpy, pandas, scipy).
Bad input raises MRFError(MRF-1003) - e.g. a non-binary target or a single-class sample.
"""

from mrf.validation.metrics import EPS, auc, brier, csi, fairness, gini, hosmer_lemeshow, ks, psi

__all__ = ["EPS", "auc", "brier", "csi", "fairness", "gini", "hosmer_lemeshow", "ks", "psi"]
