"""RebuildAgent, codegen, the parity tool and ModelRunnerImpl (registry slots ``rebuilder`` / ``runner``)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from mrf.agents.rebuild import codegen
from mrf.agents.rebuild.agent import ROLE, RebuildAgent, RebuildOutput
from mrf.agents.rebuild.execution import ScoringError, score_csv
from mrf.agents.rebuild.fixtures import load_fixture
from mrf.agents.rebuild.runner import ModelRunnerImpl
from mrf.contracts.agents import StepContext
from mrf.contracts.models import (
    ArtifactRef,
    ClassificationResult,
    Dataset,
    ModelLanguage,
    ModelRecord,
    Rebuild,
    Report,
)
from mrf.core import MRFCode, MRFError
from mrf.llm import get_mock
from mrf.mcp_server.tools.sandbox import run_parity, run_sandbox
from mrf.storage import Collections, get_blobs, get_repo

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LEGACY = Path(__file__).resolve().parents[2] / "models" / "legacy"


async def _ctx(name: str, source: Path, attempt: int = 1, **kwargs: object) -> StepContext:
    ref = await get_blobs().put_bytes(f"src/{source.name}", source.read_bytes(), filename=source.name)  # noqa: ASYNC240
    language = {".sas": ModelLanguage.SAS, ".r": ModelLanguage.R, ".py": ModelLanguage.PYTHON}[source.suffix.lower()]
    model = ModelRecord(
        model_id="mdl_" + "".join(ch for ch in name.lower() if ch.isalnum()),
        name=name,
        source_files=[ref],
        classification=ClassificationResult(
            language=language, algorithm="logistic_regression", purpose="pd", confidence=0.9, target="default_flag"
        ),
    )
    await get_repo().put(Collections.MODELS, model.model_id, model)
    return StepContext(pipeline_id="pl_t", model=model, source_files=[ref], attempt=attempt, **kwargs)  # type: ignore[arg-type]


def _wrong_reference_code() -> str:
    """Correct transcription except that age_band uses level 1 as the reference instead of 3."""
    fx = load_fixture("m001")
    frame = pd.read_csv(fx.path / "input_sample.csv")
    spec = codegen.build_spec(fx.coefficients, list(frame.columns), "logit")
    spec.levels["age_band"] = {"3": spec.levels["age_band"]["1"], "2": spec.levels["age_band"]["2"]}
    return codegen.render(spec, "M001")


# ------------------------------------------------------------------ codegen
def test_build_spec_matches_terms_to_columns() -> None:
    coef = {"intercept": -1.0, "age": 0.1, "age_band_1": 0.2, "age_band_2": 0.3, "status_A11": 0.5, "ghost_x": 1.0}
    spec = codegen.build_spec(coef, ["id", "age", "age_band", "status"], "logit")
    assert spec.intercept == -1.0 and spec.numeric == {"age": 0.1}
    assert spec.levels == {"age_band": {"1": 0.2, "2": 0.3}, "status": {"A11": 0.5}}
    assert spec.unmatched == ["ghost_x"]
    assert codegen.level_key(3.0) == codegen.level_key("3") == "3"


@pytest.mark.parametrize(("fixture", "n"), [("m001", 300), ("m002", 500), ("m004", 300)])
async def test_transcription_reproduces_every_legacy_score(fixture: str, n: int) -> None:
    fx = load_fixture(fixture)
    frame = pd.read_csv(fx.path / "input_sample.csv")
    code = codegen.render(codegen.build_spec(fx.coefficients, list(frame.columns), fx.link), fixture)
    ref = await get_blobs().put_bytes(f"cand/{fixture}.py", code.encode())
    result = await run_parity(fixture, ref.uri)
    assert result["passed"] and result["n_records"] == n and result["n_mismatches"] == 0
    assert result["max_abs_diff"] < 1e-6


# ------------------------------------------------------------------ sandbox / parity tool
async def test_sandbox_runs_large_programs_and_blocks_policy_violations() -> None:
    big = "x = '" + "a" * 200_000 + "'\nimport json\nprint(json.dumps({'n': len(x)}))"
    out = await run_sandbox(big)  # far beyond the Windows command-line limit: the program goes through stdin
    assert out["exit_code"] == 0 and out["outputs"] == {"n": 200_000}
    with pytest.raises(MRFError) as exc:
        await run_sandbox("import socket\n")
    assert exc.value.code is MRFCode.SANDBOX_POLICY


async def test_score_csv_reports_crashes() -> None:
    with pytest.raises(ScoringError) as exc:
        await score_csv("def score(input_csv):\n    raise ValueError('boom')\n", "a\n1\n")
    assert "boom" in str(exc.value)


async def test_parity_finds_the_wrong_records() -> None:
    ref = await get_blobs().put_bytes("cand/wrong.py", _wrong_reference_code().encode())
    result = await run_parity("mdl_x", ref.uri, fixture_id="m001")
    assert not result["passed"] and 0 < result["n_mismatches"] < result["n_records"]
    assert result["mismatch_examples"] and len(result["detail"]["mismatch_ids"]) == result["n_mismatches"]
    with pytest.raises(MRFError) as exc:
        await run_parity("mdl_x", ref.uri, fixture_id="nope")
    assert exc.value.code is MRFCode.NOT_FOUND


# ------------------------------------------------------------------ agent
async def test_mock_llm_falls_back_to_transcription_and_issues_certificate() -> None:
    ctx = await _ctx("M001", LEGACY / "M001_sas_pd_scorecard" / "m001_pd_scorecard.sas")
    rb = await RebuildAgent().rebuild(ctx)
    assert rb.status == "passed" and rb.parity and rb.parity.passed and rb.parity.n_records == 300
    assert rb.parity.detail["generator"] == "template" and rb.code and rb.code.sha256
    assert rb.certificate is not None
    page = (await get_blobs().get_bytes(rb.certificate.uri)).decode()
    assert "PARITY PASSED" in page and rb.code.sha256 in page
    reports = (await get_repo().find(Collections.REPORTS, Report, where={"model_id": ctx.model.model_id})).items
    assert [r.type for r in reports] == ["parity_certificate"]


async def test_llm_code_that_misses_parity_gets_actionable_feedback_then_passes() -> None:
    fx = load_fixture("m001")
    frame = pd.read_csv(fx.path / "input_sample.csv")
    good = codegen.render(codegen.build_spec(fx.coefficients, list(frame.columns), "logit"), "M001")
    prompts: list[str] = []

    def responder(messages: list, _schema: object) -> RebuildOutput:
        prompts.append(messages[-1].content)
        return RebuildOutput(code=_wrong_reference_code() if len(prompts) == 1 else good, notes=["ref coding"])

    get_mock().register(ROLE, responder)
    source = LEGACY / "M001_sas_pd_scorecard" / "m001_pd_scorecard.sas"

    first = await RebuildAgent().rebuild(await _ctx("M001", source))
    assert first.status == "failed" and first.parity and first.parity.detail["generator"] == "llm"
    assert first.usage.llm_calls == 1 and first.certificate is None
    assert any("differ from the legacy scores" in f for f in first.feedback)
    assert any("age_band" in f and "reference level" in f for f in first.feedback)  # the diagnosis names the term
    await get_repo().put(Collections.REBUILDS, first.rebuild_id, first)

    ctx = await _ctx("M001", source, attempt=2, feedback=first.feedback, artifacts={"rebuild_id": first.rebuild_id})
    second = await RebuildAgent().rebuild(ctx)
    assert second.status == "passed" and second.parity and second.parity.detail["generator"] == "llm"
    assert "FEEDBACK:" in prompts[1] and "PREVIOUS CODE" in prompts[1] and "age_band" in prompts[1]
    assert "PARAMETER ESTIMATES" in prompts[0] and "proc logistic" in prompts[0].lower()
    assert "8.182559264068665" not in prompts[0]  # column profile only - no raw rows in the prompt


async def test_policy_violation_is_feedback_not_a_crash_and_late_attempts_transcribe() -> None:
    calls: list[int] = []

    def responder(_messages: list, _schema: object) -> RebuildOutput:
        calls.append(1)
        return RebuildOutput(code="import socket\ndef score(input_csv):\n    return {'scores': []}\n")

    get_mock().register(ROLE, responder)
    source = LEGACY / "M001_sas_pd_scorecard" / "m001_pd_scorecard.sas"
    rb = await RebuildAgent().rebuild(await _ctx("M001", source))
    assert rb.status == "failed" and any("sandbox policy violation" in f for f in rb.feedback)

    late = await RebuildAgent().rebuild(await _ctx("M001", source, attempt=4))  # beyond rebuild.llm_attempts
    assert late.status == "passed" and late.parity and late.parity.detail["generator"] == "template"
    assert len(calls) == 1


async def test_no_fixture_goes_to_manual_review_and_python_needs_no_translation(tmp_path: Path) -> None:
    sas = tmp_path / "unknown_model.sas"
    sas.write_text("proc logistic data=d; model y(event='1') = x1 x2; run;")
    with pytest.raises(MRFError) as exc:
        await RebuildAgent().rebuild(await _ctx("Unnamed", sas))
    assert exc.value.code is MRFCode.INVALID_STATE and "parity fixture" in exc.value.message

    rb = await RebuildAgent().rebuild(
        await _ctx("Behaviour", LEGACY / "M003_py_xgb_behaviour" / "m003_behaviour_xgb.py")
    )
    assert rb.status == "passed" and rb.parity and "already Python" in rb.parity.detail["skipped"]
    assert rb.certificate is None


async def test_uploaded_legacy_package_is_used_as_fixture(tmp_path: Path) -> None:
    sas = tmp_path / "pricing.sas"
    sas.write_bytes((LEGACY / "M004_sas_reg_pricing" / "m004_pricing_reg.sas").read_bytes())
    ctx = await _ctx("Loan pricing", sas)
    refs: list[ArtifactRef] = list(ctx.source_files)
    for name in ("manifest.json", "input_sample.csv", "legacy_scores.csv", "coefficients.json"):
        refs.append(
            await get_blobs().put_bytes(f"src/pkg/{name}", (FIXTURES / "m004" / name).read_bytes(), filename=name)
        )
    ctx.source_files = refs
    rb = await RebuildAgent().rebuild(ctx)
    assert rb.status == "passed" and rb.parity and rb.parity.detail["fixture_id"] == ctx.model.model_id
    assert rb.parity.detail["spec"]["link"] == "identity"


# ------------------------------------------------------------------ runner
async def _rebuilt(name: str, source: Path) -> StepContext:
    ctx = await _ctx(name, source)
    rb = await RebuildAgent().rebuild(ctx)
    await get_repo().put(Collections.REBUILDS, rb.rebuild_id, rb)
    return ctx


async def _dataset(tmp_path: Path, dataset_id: str, frame: pd.DataFrame, **kwargs: object) -> Dataset:
    path = tmp_path / f"{dataset_id}.csv"
    frame.to_csv(path, index=False)
    ds = Dataset(dataset_id=dataset_id, name=dataset_id, uri=str(path), **kwargs)  # type: ignore[arg-type]
    await get_repo().put(Collections.DATASETS, ds.dataset_id, ds)
    return ds


async def test_runner_scores_measures_and_writes_outputs(tmp_path: Path) -> None:
    ctx = await _rebuilt("M001", LEGACY / "M001_sas_pd_scorecard" / "m001_pd_scorecard.sas")
    frame = pd.read_csv(FIXTURES / "m001" / "input_sample.csv").astype({"credit_amount": float})
    dev = await _dataset(tmp_path, "ds_dev", frame.iloc[:150], role="development", schema_name="german_credit_clean")
    oot = await _dataset(tmp_path, "ds_oot", frame.iloc[150:], role="out_of_time", schema_name="german_credit_clean")
    ctx.dataset_ids = [dev.dataset_id, oot.dataset_id]

    run = await ModelRunnerImpl().run(ctx, oot.dataset_id)
    m = run.metrics
    assert run.status == "succeeded" and m["n_records"] == 150 and "stub" not in m
    assert 0.5 < m["auc"] < 1 and m["gini"] == pytest.approx(2 * m["auc"] - 1)
    assert {"ks", "brier", "hosmer_lemeshow", "fairness", "observed_rate"} <= set(m)
    assert m["psi_reference"] == "dataset:ds_dev" and m["psi_score"] >= 0  # stability vs the development data
    out = pd.read_csv(get_blobs().local_path(run.outputs[0].uri))  # type: ignore[attr-defined]
    legacy = pd.read_csv(FIXTURES / "m001" / "legacy_scores.csv").iloc[150:]
    assert list(out.columns) == ["id", "score"] and out["id"].tolist() == legacy["id"].tolist()
    assert (out["score"] - legacy["pd_legacy"].to_numpy()).abs().max() < 1e-6


async def test_runner_refuses_bad_data_and_models_without_a_proven_rebuild(tmp_path: Path) -> None:
    ctx = await _rebuilt("M001", LEGACY / "M001_sas_pd_scorecard" / "m001_pd_scorecard.sas")
    frame = pd.read_csv(FIXTURES / "m001" / "input_sample.csv").astype({"credit_amount": float})
    frame.loc[0, "checking_status"] = "A99"  # unknown code: the schema check must stop the run
    bad = await _dataset(tmp_path, "ds_bad", frame, schema_name="german_credit_clean")
    with pytest.raises(MRFError) as exc:
        await ModelRunnerImpl().run(ctx, bad.dataset_id)
    assert exc.value.code is MRFCode.DATA_QUALITY_FAILED

    other = await _ctx("Nothing rebuilt", LEGACY / "M004_sas_reg_pricing" / "m004_pricing_reg.sas")
    good = await _dataset(tmp_path, "ds_ok", pd.read_csv(FIXTURES / "m004" / "input_sample.csv"))
    with pytest.raises(MRFError) as exc:
        await ModelRunnerImpl().run(other, good.dataset_id)
    assert exc.value.code is MRFCode.INVALID_STATE


async def test_runner_linear_model_reports_regression_metrics(tmp_path: Path) -> None:
    ctx = await _rebuilt("M004", LEGACY / "M004_sas_reg_pricing" / "m004_pricing_reg.sas")
    assert ctx.model.classification is not None
    ctx.model.classification.target = "price_margin"
    ds = await _dataset(tmp_path, "ds_price", pd.read_csv(FIXTURES / "m004" / "input_sample.csv"))
    run = await ModelRunnerImpl().run(ctx, ds.dataset_id)
    assert {"rmse", "mae", "r2"} <= set(run.metrics) and "auc" not in run.metrics
    assert 0.5 < run.metrics["r2"] <= 1
    stored = (await get_repo().find(Collections.REBUILDS, Rebuild, where={"model_id": ctx.model.model_id})).items
    assert json.dumps(run.metrics, default=str) and run.metrics["rebuild_id"] == stored[0].rebuild_id
