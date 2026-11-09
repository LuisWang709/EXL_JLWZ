"""mrf.validation against reference implementations (scikit-learn / scipy) and hand-computed values."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from scipy.stats import chi2, ks_2samp
from sklearn.metrics import brier_score_loss, roc_auc_score

from mrf import validation as v
from mrf.core import MRFCode, MRFError


@pytest.fixture
def scored() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(7)
    x = rng.normal(size=2000)
    p = 1 / (1 + np.exp(-(x - 1)))
    y = (rng.uniform(size=x.size) < p).astype(int)
    return y, np.round(p, 3)  # rounding creates ties on purpose


def test_auc_gini_match_sklearn(scored: tuple[np.ndarray, np.ndarray]) -> None:
    y, p = scored
    assert v.auc(y, p) == pytest.approx(roc_auc_score(y, p), abs=1e-12)
    assert v.gini(y, p) == pytest.approx(2 * roc_auc_score(y, p) - 1, abs=1e-12)


def test_auc_hand_example_with_tie() -> None:
    # pairs (bad, good): (0.9,0.1) win, (0.9,0.4) win, (0.4,0.1) win, (0.4,0.4) tie -> 3.5 / 4
    assert v.auc([1, 1, 0, 0], [0.9, 0.4, 0.4, 0.1]) == pytest.approx(0.875)


def test_ks_matches_scipy(scored: tuple[np.ndarray, np.ndarray]) -> None:
    y, p = scored
    assert v.ks(y, p) == pytest.approx(ks_2samp(p[y == 1], p[y == 0]).statistic, abs=1e-12)


def test_brier_matches_sklearn(scored: tuple[np.ndarray, np.ndarray]) -> None:
    y, p = scored
    assert v.brier(y, p) == pytest.approx(brier_score_loss(y, p), abs=1e-12)


def test_hosmer_lemeshow_hand_computed() -> None:
    p = np.array([0.1] * 10 + [0.3] * 10 + [0.6] * 10)
    y = np.array([0] * 9 + [1] + [0] * 6 + [1] * 4 + [0] * 3 + [1] * 7)
    out = v.hosmer_lemeshow(y, p, groups=3)
    # group 1: O=1 E=1 ; group 2: O=4 E=3 ; group 3: O=7 E=6
    expected = 0 + (4 - 3) ** 2 / (3 * (1 - 3 / 10)) + (7 - 6) ** 2 / (6 * (1 - 6 / 10))
    assert out["statistic"] == pytest.approx(expected)
    assert out["df"] == 1 and out["p_value"] == pytest.approx(chi2.sf(expected, 1))
    assert [g["observed"] for g in out["table"]] == [1, 4, 7]


def test_hosmer_lemeshow_well_calibrated_model_is_not_rejected(scored: tuple[np.ndarray, np.ndarray]) -> None:
    y, p = scored
    assert v.hosmer_lemeshow(y, p)["p_value"] > 0.01


def test_psi_identical_is_zero_and_known_shift() -> None:
    expected = np.arange(1000, dtype=float)  # deciles of 100 values each
    assert v.psi(expected, expected) == pytest.approx(0.0)
    actual = np.arange(500, dtype=float)  # everything falls in the first 5 deciles -> 20 % each
    shift = 5 * (0.2 - 0.1) * math.log(2) + 5 * (v.EPS - 0.1) * math.log(v.EPS / 0.1)
    assert v.psi(expected, actual) == pytest.approx(shift, rel=1e-9)


def test_psi_categorical_and_low_cardinality() -> None:
    e = pd.Series(["A"] * 50 + ["B"] * 50)
    a = pd.Series(["A"] * 80 + ["B"] * 20)
    hand = (0.8 - 0.5) * math.log(0.8 / 0.5) + (0.2 - 0.5) * math.log(0.2 / 0.5)
    assert v.psi(e, a) == pytest.approx(hand)
    # integer bands vs float bands are the same bins
    assert v.psi(pd.Series([1, 2, 3] * 10), pd.Series([1.0, 2.0, 3.0] * 10)) == pytest.approx(0.0)


def test_psi_missing_values_form_their_own_bin() -> None:
    e = pd.Series([1.0, 2.0, 3.0, 4.0] * 25)
    a = pd.Series([1.0, 2.0, 3.0, np.nan] * 25)
    assert v.psi(e, a) > 0.5


def test_csi_per_column_and_missing_column_error() -> None:
    base = pd.DataFrame({"x": np.arange(100.0), "c": ["u", "v"] * 50})
    out = v.csi(base, base, columns=["x", "c"])
    assert out == pytest.approx({"x": 0.0, "c": 0.0})
    with pytest.raises(MRFError) as err:
        v.csi(base, base.drop(columns="c"), columns=["c"])
    assert err.value.code == MRFCode.INPUT_DATA_SCHEMA


def test_fairness_disparate_impact_and_gaps() -> None:
    # segment a: never flagged; segment b: half flagged (the bads)
    y = [0, 0, 0, 0, 1, 1, 0, 0]
    score = [0.1, 0.1, 0.1, 0.1, 0.9, 0.9, 0.1, 0.1]
    seg = ["a", "a", "a", "a", "b", "b", "b", "b"]
    out = v.fairness(y, score, seg, threshold=0.5)
    assert out["segments"]["a"]["approval_rate"] == 1.0
    assert out["segments"]["b"]["approval_rate"] == 0.5
    assert out["disparate_impact"] == pytest.approx(0.5)
    assert out["reference_segment"] == "a"
    assert out["segments"]["a"]["tpr"] is None and out["segments"]["b"]["tpr"] == 1.0
    assert out["segments"]["b"]["auc"] == 1.0


def test_fairness_default_threshold_flags_the_bad_rate(scored: tuple[np.ndarray, np.ndarray]) -> None:
    y, p = scored
    seg = np.where(np.arange(y.size) % 2 == 0, "even", "odd")
    out = v.fairness(y, p, seg)
    flagged = sum(s["flag_rate"] * s["n"] for s in out["segments"].values()) / out["n"]
    assert flagged == pytest.approx(y.mean(), abs=0.02)


@pytest.mark.parametrize(
    ("y", "s"),
    [([0, 1, 2], [0.1, 0.2, 0.3]), ([1, 1, 1], [0.1, 0.2, 0.3]), ([0, 1], [0.1, 0.2, 0.3])],
)
def test_bad_input_raises_mrf_1003(y: list[int], s: list[float]) -> None:
    with pytest.raises(MRFError) as err:
        v.auc(y, s)
    assert err.value.code == MRFCode.INPUT_DATA_SCHEMA


def test_missing_rows_are_dropped() -> None:
    assert v.auc([1, 0, np.nan, 1], [0.9, 0.1, 0.5, np.nan]) == 1.0


def test_brier_rejects_non_probabilities() -> None:
    with pytest.raises(MRFError):
        v.brier([0, 1], [0.2, 1.4])
