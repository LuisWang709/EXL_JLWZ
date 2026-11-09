"""Classifier: static parsers + agent (mock LLM) against the A1 gold set in tests/fixtures/classify/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mrf.agents.classify.agent import ClassifierAgent, LLMClassification, fuse
from mrf.agents.classify.parsers import detect_language, parse_python, parse_r, parse_sas, parse_source
from mrf.contracts.agents import StepContext
from mrf.contracts.models import ModelRecord
from mrf.core import MRFCode, MRFError
from mrf.llm import get_mock
from mrf.mcp_server.tools.inventory import parse_code
from mrf.storage import get_blobs

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "classify"
GOLD: dict[str, dict[str, Any]] = {k: v for k, v in json.loads((FIX / "gold.json").read_text()).items() if k[0] != "_"}


@pytest.mark.parametrize("filename", sorted(GOLD))
def test_parsers_match_gold(filename: str) -> None:
    gold = GOLD[filename]
    p = parse_source(filename, (FIX / filename).read_bytes())
    assert (p.language, p.algorithm, p.target, p.purpose_hint) == (
        gold["language"],
        gold["algorithm"],
        gold["target"],
        gold["purpose"],
    )
    assert p.features == gold["features"]
    assert any(s.kind == "model" for s in p.statements)


def test_sas_comments_keep_line_numbers_and_reference_levels() -> None:
    code = (
        "/* header\n spans */\n* proc reg data=x; model a = b; run;\nproc logistic data=d;\n"
        "  class grade(ref='A') / param=ref;\n  model bad = grade income;\nrun;\n"
    )
    p = parse_sas(code)
    assert p.procedures == ["PROC LOGISTIC"]  # commented-out PROC REG ignored
    model = next(s for s in p.statements if s.kind == "model")
    assert model.line_start == 6 and p.class_variables == {"grade": "A"}
    assert "CLASS uses reference coding (param=ref)" in p.warnings


def test_sas_effect_coding_warning_and_genmod_binomial() -> None:
    p = parse_sas("proc genmod data=d; class g; model y = g x / dist=binomial link=logit; run;")
    assert p.algorithm == "logistic_regression"
    assert any("effect coding" in w for w in p.warnings)


def test_r_dot_formula_and_comment_hash_in_string() -> None:
    p = parse_r('x <- "a#b"  # comment with glm(\nfit <- glm(bad ~ ., family=binomial, data=train)\n')
    assert p.algorithm == "logistic_regression" and p.target == "bad"
    assert any("'.'" in w for w in p.warnings) and p.procedures == ["glm(family=binomial)"]


def test_python_statsmodels_formula_and_syntax_error_fallback() -> None:
    p = parse_python('import statsmodels.formula.api as smf\nm = smf.logit("default ~ age + income", data=df).fit()\n')
    assert (p.algorithm, p.target, p.features) == ("logistic_regression", "default", ["age", "income"])
    broken = parse_python("model = LogisticRegression(\n")
    assert broken.algorithm == "logistic_regression" and broken.warnings


def test_detect_language_without_suffix() -> None:
    assert detect_language("model.txt", "proc logistic data=a;\nmodel y=x;\nrun;\n") == "sas"
    assert detect_language("model.txt", "library(dplyr)\nfit <- glm(y ~ x)\n") == "r"
    assert detect_language("model.txt", "hello world") == "unknown"


async def test_parse_code_tool_errors() -> None:
    ref = await get_blobs().put_bytes("x/notes.txt", b"just some words")
    with pytest.raises(MRFError) as e:
        await parse_code(ref.uri)
    assert e.value.code is MRFCode.CODE_UNPARSEABLE
    ref = await get_blobs().put_bytes("x/blob.sas", b"\x00\x01\x02")
    with pytest.raises(MRFError) as e:
        await parse_code(ref.uri)
    assert e.value.code is MRFCode.CODE_UNPARSEABLE


async def _ctx(*filenames: str, contents: dict[str, bytes] | None = None) -> StepContext:
    refs = []
    for name in filenames:
        data = (contents or {}).get(name) or (FIX / name).read_bytes()
        refs.append(await get_blobs().put_bytes(f"models/m/source/{name}", data, filename=name))
    model = ModelRecord(model_id="mdl_t", name=filenames[0], source_files=refs)
    return StepContext(pipeline_id="pl_t", model=model, source_files=refs)


async def test_agent_identifies_all_gold_models_with_high_confidence() -> None:
    correct = 0
    for name, gold in GOLD.items():
        result = await ClassifierAgent().classify(await _ctx(name))
        hit = (result.language.value, result.algorithm, result.purpose, result.target) == (
            gold["language"],
            gold["algorithm"],
            gold["purpose"],
            gold["target"],
        )
        correct += hit
        assert result.confidence >= 0.7 and not result.needs_review, (name, result.metadata["confidence_parts"])
        assert any(e.source == "code" and e.ref.startswith(name) for e in result.evidence)
        assert any(e.source == "tool" for e in result.evidence)
    assert correct == len(GOLD)


async def test_llm_disagreement_drops_below_threshold() -> None:
    get_mock().register(
        "classifier", {"algorithm": "random_forest", "purpose": "pd", "cited_lines": [999], "confidence": 0.9}
    )
    result = await ClassifierAgent().classify(await _ctx("m001_pd_scorecard.sas"))
    assert result.needs_review and result.confidence < 0.7
    assert result.metadata["confidence_parts"]["agree"] == 0.6
    assert result.algorithm == "logistic_regression"  # parser stays authoritative


async def test_broken_code_needs_review() -> None:
    ctx = await _ctx("broken.sas", contents={"broken.sas": b"data a; set b; x = 1; run;\n"})
    result = await ClassifierAgent().classify(ctx)
    assert result.needs_review


async def test_picks_model_file_among_several_and_ignores_readme() -> None:
    ctx = await _ctx(
        "README.md",
        "helpers.R",
        "m002_card_default.R",
        contents={"README.md": b"# readme", "helpers.R": b"f <- function(x) x + 1\n"},
    )
    result = await ClassifierAgent().classify(ctx)
    assert result.algorithm == "logistic_regression" and result.metadata["files"] == [
        "helpers.R",
        "m002_card_default.R",
    ]


async def test_no_code_files_is_unparseable() -> None:
    with pytest.raises(MRFError) as e:
        await ClassifierAgent().classify(await _ctx("README.md", contents={"README.md": b"# hi"}))
    assert e.value.code is MRFCode.CODE_UNPARSEABLE


def test_fusion_formula() -> None:
    rule = {"language": "sas", "algorithm": "logistic_regression", "target": "y", "features": ["x"]}
    llm = LLMClassification(algorithm="scorecard", purpose="pd", cited_lines=[1], confidence=1.0)
    c, parts = fuse(rule, llm, n_lines=10)
    assert parts == {"c_rule": 1.0, "c_llm": 1.0, "agree": 1.0, "cited_ok": 1.0} and c == 1.0
    c2, _ = fuse({**rule, "algorithm": "unknown"}, llm, n_lines=10)
    assert c2 == pytest.approx(0.8 * (0.6 * 0.6 + 0.4))
