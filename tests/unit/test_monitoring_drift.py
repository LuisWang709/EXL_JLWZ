"""Thresholds and column selection (A4). Values come from config/pipeline.yaml monitoring."""

from __future__ import annotations

import pytest

from mrf.contracts.models import ClassificationResult, ColumnInfo, Dataset, ModelLanguage, ModelRecord
from mrf.core import MRFCode, MRFError
from mrf.monitoring import drift
from tests.unit.monitoring_helpers import frame, use_fake_validation


@pytest.mark.parametrize(
    ("psi", "expected"),
    [(0.0999, "green"), (0.10, "amber"), (0.25, "amber"), (0.2501, "red")],
)
def test_psi_boundaries(psi: float, expected: str) -> None:
    status, reasons = drift.classify({"x1": psi, "x2": 0.0})
    assert status == expected
    assert bool(reasons) == (expected != "green")


def test_gini_drop_over_five_points_is_red_even_without_psi_drift() -> None:
    assert drift.classify({"x1": 0.01}, gini=0.449, baseline_gini=0.50)[0] == "red"  # drop 0.051
    assert drift.classify({"x1": 0.01}, gini=0.451, baseline_gini=0.50)[0] == "green"  # drop 0.049


def test_reason_names_the_worst_column_and_score() -> None:
    _, reasons = drift.classify({"x1": 0.12, drift.SCORE_KEY: 0.31})
    assert reasons == ["PSI 0.310 on score > 0.25"]


def test_thresholds_come_from_policy() -> None:
    policy = drift.thresholds()
    assert (policy["psi_amber"], policy["psi_red"], policy["gini_drop_red"]) == (0.10, 0.25, 0.05)


def test_pick_features_excludes_ids_and_targets() -> None:
    model = ModelRecord(model_id="m", name="m")
    base = Dataset(dataset_id="b", name="b", uri="b.csv")
    assert drift.pick_features(model, base, frame(), frame()) == ["x1", "x2"]


def test_pick_features_prefers_classifier_features_and_declared_roles() -> None:
    cls = ClassificationResult(
        language=ModelLanguage.SAS, algorithm="lr", purpose="pd", confidence=0.9, features=["x2", "not_in_data"]
    )
    assert drift.pick_features(
        ModelRecord(model_id="m", name="m", classification=cls),
        Dataset(dataset_id="b", name="b", uri="b.csv"),
        frame(),
        frame(),
    ) == ["x2"]
    declared = Dataset(
        dataset_id="b", name="b", uri="b.csv", columns=[ColumnInfo(name="x1", dtype="float", role="score")]
    )
    assert drift.pick_features(ModelRecord(model_id="m", name="m"), declared, frame(), frame()) == ["x2"]


def test_compute_psi_uses_validation_library(monkeypatch: pytest.MonkeyPatch) -> None:
    use_fake_validation(monkeypatch)
    base, batch = frame(), frame(shift=0.3)
    out = drift.compute_psi(base, batch, ["x1"], base["x1"], batch["x1"])
    assert out["x1"] == pytest.approx(0.3) and out[drift.SCORE_KEY] == pytest.approx(0.3)


def test_missing_validation_library_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    monkeypatch.setattr(drift.importlib, "import_module", lambda name: types.ModuleType(name))
    with pytest.raises(MRFError) as err:
        drift.compute_psi(frame(), frame(), ["x1"])
    assert err.value.code == MRFCode.INTERNAL and "A3" in err.value.message
