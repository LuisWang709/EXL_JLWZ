"""Validation metrics: discrimination, calibration, stability, fairness. Owner: A3.

Pure functions on array-likes (lists, numpy arrays, pandas Series). Signatures are frozen with contract v1:
A2's usability run, A4's monitoring (PSI/CSI) and the ``compute_metrics`` MCP tool all call these.

Conventions
* ``y_true``: 1 = event (default / bad), 0 = non-event. Anything else -> MRF-1003.
* ``score`` / ``prob``: higher = riskier. An AUC below 0.5 means the score is reverse-oriented
  (e.g. scorecard points where higher = safer); the caller decides whether to negate it.
* Rows where ``y_true`` or the score is missing are dropped before computing.
* PSI / CSI: bins come from the *expected* (reference) distribution. A share of 0 in a bin is replaced by
  ``EPS`` so the logarithm stays finite. Missing values form their own bin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from mrf.core import MRFCode, MRFError

if TYPE_CHECKING:
    import pandas as pd

#: replaces an empty bin share in PSI / CSI (industry convention: 1e-4)
EPS = 1e-4
_MISSING = "__missing__"
_OTHER = "__other__"


# ---------------------------------------------------------------------------------------------- helpers
def _bad(message: str, field: str | None = None) -> MRFError:
    return MRFError(MRFCode.INPUT_DATA_SCHEMA, message, field=field)


def _xy(y_true: Any, score: Any, score_name: str = "score") -> tuple[np.ndarray, np.ndarray]:
    try:
        y = np.asarray(y_true, dtype=float).ravel()
        s = np.asarray(score, dtype=float).ravel()
    except (TypeError, ValueError) as exc:
        raise _bad(f"y_true and {score_name} must be numeric: {exc}") from exc
    if y.shape != s.shape:
        raise _bad(f"y_true has {y.size} values but {score_name} has {s.size}")
    keep = ~(np.isnan(y) | np.isnan(s))
    y, s = y[keep], s[keep]
    if y.size == 0:
        raise _bad("no rows left after dropping missing values")
    if not np.isin(y, (0.0, 1.0)).all():
        raise _bad("y_true must be binary (0 = good, 1 = bad)", field="y_true")
    return y, s


def _both_classes(y: np.ndarray) -> tuple[float, float]:
    n_pos = float(y.sum())
    n_neg = float(y.size - n_pos)
    if n_pos == 0 or n_neg == 0:
        raise _bad("y_true needs both classes (at least one 0 and one 1)", field="y_true")
    return n_pos, n_neg


def _check_prob(p: np.ndarray, name: str = "prob") -> None:
    if (p < 0).any() or (p > 1).any():
        raise _bad(f"{name} must lie within [0, 1]", field=name)


# ---------------------------------------------------------------------------------------------- discrimination
def auc(y_true: Any, score: Any) -> float:
    """Area under the ROC curve (Mann-Whitney U with average ranks for ties)."""
    from scipy.stats import rankdata

    y, s = _xy(y_true, score)
    n_pos, n_neg = _both_classes(y)
    ranks = rankdata(s)  # average ranks -> ties count one half
    u = ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2
    return float(u / (n_pos * n_neg))


def gini(y_true: Any, score: Any) -> float:
    """Gini coefficient (accuracy ratio) = 2 * AUC - 1."""
    return 2.0 * auc(y_true, score) - 1.0


def ks(y_true: Any, score: Any) -> float:
    """Kolmogorov-Smirnov statistic: largest gap between the score CDFs of bads and goods."""
    y, s = _xy(y_true, score)
    n_pos, n_neg = _both_classes(y)
    order = np.argsort(s, kind="mergesort")
    s_sorted, y_sorted = s[order], y[order]
    cum_pos = np.cumsum(y_sorted) / n_pos
    cum_neg = np.cumsum(1.0 - y_sorted) / n_neg
    last_of_tie = np.r_[s_sorted[1:] != s_sorted[:-1], True]  # evaluate only between distinct scores
    return float(np.max(np.abs(cum_pos[last_of_tie] - cum_neg[last_of_tie])))


# ---------------------------------------------------------------------------------------------- calibration
def brier(y_true: Any, prob: Any) -> float:
    """Brier score: mean squared error of predicted probabilities (lower is better)."""
    y, p = _xy(y_true, prob, "prob")
    _check_prob(p)
    return float(np.mean((p - y) ** 2))


def hosmer_lemeshow(y_true: Any, prob: Any, groups: int = 10) -> dict[str, Any]:
    """Hosmer-Lemeshow goodness-of-fit test.

    Observations are sorted by predicted probability and split into ``groups`` equal-count groups
    ("deciles of risk"). statistic = sum((O - E)^2 / (E * (1 - E / n))) over groups, df = groups - 2.

    Returns {"statistic", "p_value", "df", "groups", "table": [{group, n, observed, expected, mean_prob,
    min_prob, max_prob}]}. A small p-value (< 0.05) indicates poor calibration.
    """
    from scipy.stats import chi2

    if groups < 3:
        raise MRFError(MRFCode.INPUT_BODY, "groups must be at least 3", field="groups")
    y, p = _xy(y_true, prob, "prob")
    _check_prob(p)
    if y.size < groups:
        raise _bad(f"need at least {groups} rows for {groups} groups, got {y.size}")
    order = np.argsort(p, kind="mergesort")
    statistic = 0.0
    table: list[dict[str, Any]] = []
    for i, idx in enumerate(np.array_split(order, groups), start=1):
        n = int(idx.size)
        observed = float(y[idx].sum())
        expected = float(p[idx].sum())
        variance = expected * (1.0 - expected / n)
        if variance > 0:
            statistic += (observed - expected) ** 2 / variance
        table.append(
            {
                "group": i,
                "n": n,
                "observed": observed,
                "expected": expected,
                "mean_prob": expected / n,
                "min_prob": float(p[idx].min()),
                "max_prob": float(p[idx].max()),
            }
        )
    df = groups - 2
    return {
        "statistic": float(statistic),
        "p_value": float(chi2.sf(statistic, df)),
        "df": df,
        "groups": groups,
        "table": table,
    }


# ---------------------------------------------------------------------------------------------- stability
def _series(values: Any) -> pd.Series:
    import pandas as pd

    if isinstance(values, pd.Series):
        return values.reset_index(drop=True)
    return pd.Series(np.asarray(values).ravel())


def _is_numeric(s: pd.Series) -> bool:
    import pandas as pd

    return bool(pd.api.types.is_numeric_dtype(s)) and not pd.api.types.is_bool_dtype(s)


def _text_labels(s: pd.Series, categories: set[str]) -> np.ndarray:
    """Categorical labels by text value; unseen values -> _OTHER, missing -> _MISSING."""
    text = s.astype(str)
    labels = np.where(text.isin(categories).to_numpy(), text.to_numpy(), _OTHER).astype(object)
    labels[s.isna().to_numpy()] = _MISSING
    return labels


def _value_labels(s: pd.Series, values: np.ndarray) -> np.ndarray:
    """One label per distinct numeric value (1 and 1.0 are the same bin); unseen -> _OTHER, NaN -> _MISSING."""
    v = s.to_numpy(dtype=float)
    labels = np.full(v.shape, _OTHER, dtype=object)
    known = np.isin(v, values)
    labels[known] = v[known]
    labels[np.isnan(v)] = _MISSING
    return labels


def _bin_labels(expected: pd.Series, actual: pd.Series, bins: int, binning: str) -> tuple[np.ndarray, np.ndarray]:
    """Bin both series using cut points learned on ``expected``. Returns bin labels for each."""
    numeric = _is_numeric(expected) and _is_numeric(actual)
    if not numeric:
        categories = {str(v) for v in expected.dropna().unique()}
        return _text_labels(expected, categories), _text_labels(actual, categories)

    e_valid = expected.dropna().to_numpy(dtype=float)
    distinct = np.unique(e_valid)
    if distinct.size <= bins:  # low-cardinality numeric (e.g. age_band 1/2/3): one bin per value
        return _value_labels(expected, distinct), _value_labels(actual, distinct)

    if binning == "quantile":
        cuts = np.quantile(e_valid, np.linspace(0, 1, bins + 1)[1:-1])
    elif binning in {"uniform", "equal_width"}:
        cuts = np.linspace(e_valid.min(), e_valid.max(), bins + 1)[1:-1]
    else:
        raise MRFError(MRFCode.INPUT_BODY, f"unknown binning {binning!r}; use 'quantile' or 'uniform'", field="binning")
    cuts = np.unique(cuts)

    def assign(s: pd.Series) -> np.ndarray:
        values = s.to_numpy(dtype=float)
        idx = np.searchsorted(cuts, values, side="left")  # bins are (cut[i-1], cut[i]]
        labels = idx.astype(object)
        labels[np.isnan(values)] = _MISSING
        return labels

    return assign(expected), assign(actual)


def _shares(labels: np.ndarray, keys: list[Any]) -> np.ndarray:
    counts = np.array([np.sum(labels == k) for k in keys], dtype=float)
    return counts / counts.sum()


def psi(expected: Any, actual: Any, bins: int = 10, binning: str = "quantile") -> float:
    """Population Stability Index between a reference (``expected``) and a new (``actual``) sample.

    PSI = sum((a_i - e_i) * ln(a_i / e_i)) over bins. Numeric variables with more than ``bins`` distinct values
    are cut at quantiles (or equal widths with ``binning='uniform'``) of the reference sample; categorical and
    low-cardinality variables use one bin per value. Rule of thumb: < 0.10 stable, 0.10-0.25 moderate shift,
    > 0.25 significant shift (thresholds live in config/pipeline.yaml, monitoring.*).
    """
    if bins < 2:
        raise MRFError(MRFCode.INPUT_BODY, "bins must be at least 2", field="bins")
    e, a = _series(expected), _series(actual)
    if len(e) == 0 or len(a) == 0:
        raise _bad("expected and actual must both be non-empty")
    e_labels, a_labels = _bin_labels(e, a, bins, binning)
    keys = sorted({*e_labels.tolist(), *a_labels.tolist()}, key=str)
    e_share = np.where((s := _shares(e_labels, keys)) == 0, EPS, s)
    a_share = np.where((s := _shares(a_labels, keys)) == 0, EPS, s)
    return float(np.sum((a_share - e_share) * np.log(a_share / e_share)))


def csi(
    expected_df: pd.DataFrame, actual_df: pd.DataFrame, columns: list[str] | None = None, bins: int = 10
) -> dict[str, float]:
    """Characteristic Stability Index: PSI of each feature. Default columns: those present in both frames."""
    cols = list(columns) if columns is not None else [c for c in expected_df.columns if c in actual_df.columns]
    missing = [c for c in cols if c not in expected_df.columns or c not in actual_df.columns]
    if missing:
        raise _bad(f"columns missing from one of the frames: {missing}", field="columns")
    return {c: psi(expected_df[c], actual_df[c], bins=bins) for c in cols}


# ---------------------------------------------------------------------------------------------- fairness
def fairness(y_true: Any, score: Any, segment: Any, threshold: float | None = None) -> dict[str, Any]:
    """Outcome parity across segments (e.g. age bands) for a risk score where higher = riskier.

    A case is *flagged* (would be declined) when ``score >= threshold``. Default threshold: the score quantile
    that flags the same share of cases as the overall observed bad rate.

    Returns::

        {"threshold": float, "n": int, "reference_segment": str,
         "disparate_impact": float,   # min / max approval rate across segments (four-fifths rule: >= 0.8)
         "max_tpr_gap": float,         # equal opportunity gap: spread of the bad-capture rate
         "max_fpr_gap": float,         # spread of the share of goods that are declined
         "segments": {name: {"n", "share", "bad_rate", "mean_score", "flag_rate", "approval_rate",
                             "adverse_impact_ratio", "tpr", "fpr", "auc"}}}

    ``tpr`` / ``fpr`` / ``auc`` are ``None`` for a segment without both classes.
    """
    import pandas as pd

    y_raw = np.asarray(y_true, dtype=float).ravel()
    s_raw = np.asarray(score, dtype=float).ravel()
    seg_raw = _series(segment)
    if not (y_raw.size == s_raw.size == len(seg_raw)):
        raise _bad("y_true, score and segment must have the same length")
    keep = ~(np.isnan(y_raw) | np.isnan(s_raw))
    y, s = _xy(y_raw[keep], s_raw[keep])
    seg = seg_raw[keep].reset_index(drop=True)
    seg_labels = np.where(seg.isna().to_numpy(), _MISSING, seg.astype(str).to_numpy())

    if threshold is None:
        bad_rate = float(y.mean())
        threshold = float(np.quantile(s, 1.0 - bad_rate)) if 0 < bad_rate < 1 else float(np.median(s))
    flagged = s >= threshold

    segments: dict[str, dict[str, Any]] = {}
    for name in sorted(pd.unique(seg_labels), key=str):
        m = seg_labels == name
        ys, ss, fs = y[m], s[m], flagged[m]
        n_bad, n_good = float(ys.sum()), float(ys.size - ys.sum())
        segments[str(name)] = {
            "n": int(m.sum()),
            "share": float(m.mean()),
            "bad_rate": float(ys.mean()),
            "mean_score": float(ss.mean()),
            "flag_rate": float(fs.mean()),
            "approval_rate": float(1.0 - fs.mean()),
            "tpr": float(fs[ys == 1].mean()) if n_bad else None,
            "fpr": float(fs[ys == 0].mean()) if n_good else None,
            "auc": auc(ys, ss) if n_bad and n_good else None,
        }

    approvals = {k: v["approval_rate"] for k, v in segments.items()}
    best = max(approvals.values())
    for v in segments.values():
        v["adverse_impact_ratio"] = v["approval_rate"] / best if best > 0 else None
    tprs = [v["tpr"] for v in segments.values() if v["tpr"] is not None]
    fprs = [v["fpr"] for v in segments.values() if v["fpr"] is not None]
    return {
        "threshold": float(threshold),
        "n": int(y.size),
        "reference_segment": max(approvals, key=lambda k: approvals[k]),
        "disparate_impact": float(min(approvals.values()) / best) if best > 0 else None,
        "max_tpr_gap": float(max(tprs) - min(tprs)) if len(tprs) > 1 else 0.0,
        "max_fpr_gap": float(max(fprs) - min(fprs)) if len(fprs) > 1 else 0.0,
        "segments": segments,
    }


__all__ = ["EPS", "auc", "brier", "csi", "fairness", "gini", "hosmer_lemeshow", "ks", "psi"]
