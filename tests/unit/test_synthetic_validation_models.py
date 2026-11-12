"""The shipped R/SAS packages remain complete, reproducible and in their advertised validation bands."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scripts.generate_validation_models import PACKAGE_FILES, generate, scores

from mrf import validation as v
from mrf.agents.classify.parsers import parse_source
from mrf.config import REPO_ROOT
from mrf.contracts.models import ModelRecord, ParityResult, Rebuild, Run
from mrf.core import guards
from mrf.reporting.builder import Inputs, assemble

ROOT = REPO_ROOT / "models" / "synthetic_validation"
CASES = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))["models"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_shipped_package_reproduces_scores_and_report_colour(case: dict) -> None:
    folder = ROOT / case["path"]
    upload = folder / "upload_together"
    source = folder / case["source"]
    parsed = parse_source(source.name, source.read_bytes())
    assert parsed.language == case["language"].lower()
    assert set(parsed.features) == {"risk_driver", "utilisation"} and parsed.target == "default_flag"
    for path in upload.iterdir():
        assert guards.scan_file(path.name, path.read_bytes()) == []
    manifest = json.loads((upload / "manifest.json").read_text())
    assert manifest["synthetic"] and manifest["model_id"] == case["name"]
    coefficients = json.loads((upload / "coefficients.json").read_text())
    sample = pd.read_csv(upload / "input_sample.csv")
    actual = pd.read_csv(folder / "validation.csv")
    development = pd.read_csv(folder / "development.csv")
    pd.testing.assert_frame_equal(sample, actual)
    assert set(actual.id).isdisjoint(development.id)
    expected = pd.read_csv(upload / "legacy_scores.csv")
    assert actual.id.tolist() == expected.id.tolist()
    predicted = scores(actual, coefficients)
    mismatches = int((np.abs(predicted - expected.pd_legacy.to_numpy()) > manifest["tolerance"]).sum())
    assert len(actual) == 900 and mismatches == 0
    metrics = {"gini": v.gini(actual.default_flag, predicted), "hosmer_lemeshow": v.hosmer_lemeshow(
        actual.default_flag, predicted,
    ), "psi_score": v.psi(scores(development, coefficients), predicted)}
    gini = metrics["gini"]
    if case["expected_rag"] == "green":
        assert gini >= 0.4
    elif case["expected_rag"] == "amber":
        assert 0.3 <= gini < 0.4
    else:
        assert gini < 0.3
    inputs = Inputs(
        model=ModelRecord(model_id=case["name"], name=case["name"]),
        rebuild=Rebuild(rebuild_id="synthetic", model_id=case["name"], attempt=1, parity=ParityResult(
            passed=mismatches == 0, n_records=len(actual), n_mismatches=mismatches,
        )),
        runs=[Run(run_id="synthetic", model_id=case["name"], dataset_id="validation", metrics=metrics)],
        fairness=v.fairness(actual.default_flag, predicted, actual.age_band),
    )
    _, _, view = assemble(inputs)
    assert view["overall"] == case["expected_rag"]
    assert view["statuses"] == {"performance": case["expected_rag"], "consistency": "green",
                                "stability": "green", "fairness": "green"}
    recorded = json.loads((folder / "verification.json").read_text())
    assert recorded["actual_rag"] == case["expected_rag"] and recorded["n_parity_mismatches"] == 0


def test_generator_recreates_versioned_sources_and_synthetic_data(tmp_path: Path) -> None:
    cases = generate(tmp_path / "regenerated")
    assert len(cases) == 6
    for case in cases:
        generated = tmp_path / "regenerated" / case["path"]
        shipped = ROOT / case["path"]
        for filename in ("development.csv", "validation.csv", case["source"], *(
            f"upload_together/{f}" for f in PACKAGE_FILES
        )):
            assert (generated / filename).read_text(encoding="utf-8") == (
                shipped / filename
            ).read_text(encoding="utf-8")
