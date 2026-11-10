"""DocRater calibration: the agent's M001 document passes, deliberately broken variants fail."""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest

from mrf.agents.doc.agent import DocAgent
from mrf.config import get_policy
from mrf.contracts.agents import StepContext
from mrf.contracts.models import Document
from mrf.llm import get_mock
from mrf.rating.checks import number_supported, number_tokens
from mrf.rating.rater import DocRater
from mrf.rating.rubric import SECTION_TITLES, load_rubric, required_sections
from tests.unit.a3_helpers import broken_copy, m001_context


@pytest.fixture
async def drafted() -> tuple[StepContext, Document]:
    ctx = await m001_context()
    return ctx, await DocAgent().draft(ctx)


def test_rubric_matches_pipeline_policy() -> None:
    rubric, policy = load_rubric(), get_policy()["rating"]
    assert sum(v["weight"] for v in rubric["rule_checks"].values()) == policy["rule_weight"]
    assert sum(rubric["llm_review"].values()) == policy["llm_weight"]
    assert rubric["pass_score"] == policy["pass_score"] and sorted(rubric["veto"]) == sorted(policy["veto_flags"])
    assert required_sections() == list(SECTION_TITLES)


async def test_agent_document_passes(drafted: tuple[StepContext, Document]) -> None:
    ctx, doc = drafted
    rating = await DocRater().rate(ctx, doc)
    assert rating.passed and not rating.veto_flags, rating.comments
    assert rating.rule_score == 60 and rating.total >= 80 and rating.attempt == doc.attempt
    assert rating.breakdown["evidence_coverage"] == 20 and rating.breakdown["variable_consistency"] == 20


def _drop_sections(doc: Document) -> Document:
    return broken_copy(doc, sections={k: doc.sections[k] for k in ("purpose_and_use", "data")})


def _strip_citations(doc: Document) -> Document:
    return broken_copy(doc, sections={k: re.sub(r"\[E\d+\]", "", v) for k, v in doc.sections.items()})


def _fabricated_variable(doc: Document) -> Document:
    sections = dict(doc.sections)
    sections["data"] += "\n- Annual income `annual_income` is the strongest driver of default. [E1]"
    return broken_copy(doc, sections=sections)


def _fabricated_number(doc: Document) -> Document:
    sections = dict(doc.sections)
    sections["performance"] += "\n- The model reaches a Gini of 0.87 on the out-of-time sample. [E1]"
    return broken_copy(doc, sections=sections)


def _undocumented_variable(doc: Document) -> Document:
    sections = {
        k: "\n".join(line for line in v.split("\n") if "log_amount" not in line) for k, v in doc.sections.items()
    }
    sections["data"] += "\n- `duration_months` and `age_band` are also used. [E1]"
    return broken_copy(doc, sections=sections)


@pytest.mark.parametrize(
    ("breaker", "veto", "comment"),
    [
        (_drop_sections, [], "Add the 'Monitoring' section"),
        (_strip_citations, [], "cite evidence for"),
        (_fabricated_variable, ["fabricated_variable"], "`annual_income`"),
        (_fabricated_number, ["fabricated_number"], "0.87 (Performance)"),
    ],
)
async def test_broken_documents_fail(
    drafted: tuple[StepContext, Document], breaker: Callable[[Document], Document], veto: list[str], comment: str
) -> None:
    ctx, doc = drafted
    rating = await DocRater().rate(ctx, breaker(doc))
    assert not rating.passed
    assert rating.veto_flags == veto
    assert any(comment in c for c in rating.comments), rating.comments
    assert len(rating.comments) <= load_rubric()["max_comments"]


async def test_undocumented_model_variable_costs_points(drafted: tuple[StepContext, Document]) -> None:
    ctx, doc = drafted
    rating = await DocRater().rate(ctx, _undocumented_variable(doc))
    assert rating.breakdown["variable_consistency"] == pytest.approx(16.0)
    assert any("`log_amount`" in c for c in rating.comments)


async def test_tampered_evidence_is_detected(drafted: tuple[StepContext, Document]) -> None:
    ctx, doc = drafted
    evidence = [e.model_copy() for e in doc.evidence]
    i = next(i for i, e in enumerate(evidence) if e.ref == "m001_pd_scorecard.sas:16-21")
    evidence[i].quote = "proc logistic data=x; model default_flag = income;"
    kb = next(i for i, e in enumerate(evidence) if e.source == "kb")
    evidence[kb].ref = "kb:no_such_chunk#1"
    rating = await DocRater().rate(ctx, broken_copy(doc, evidence=evidence))
    assert any(f"[E{i + 1}]" in c and "quote not found in the code" in c for c in rating.comments)
    assert any(f"[E{kb + 1}]" in c and "unknown knowledge-base chunk" in c for c in rating.comments)


async def test_llm_reviewer_is_clamped_and_independent(drafted: tuple[StepContext, Document]) -> None:
    ctx, doc = drafted
    get_mock().register(
        "rater", {"methodology_accuracy": 99, "limitations_adequacy": -5, "clarity": 10, "comments": ["Be specific."]}
    )
    rating = await DocRater().rate(ctx, doc)
    assert rating.llm_score == 25 and rating.breakdown["methodology_accuracy"] == 15
    assert "Be specific." in rating.comments
    call = next(c for c in get_mock().calls if c.role == "rater")
    assert "independent model validator" in call.messages[0].content
    assert "PARSER SUMMARY (ground truth)" in call.messages[-1].content
    assert "model documentation specialist" not in call.messages[0].content


@pytest.mark.parametrize(
    ("text", "allowed", "ok"),
    [
        ("Gini 0.542", [0.54213], True),
        ("Gini 0.542", [0.5], False),
        ("missing 2.0%", [0.02], True),
        ("tolerance 1e-06", [1e-06], True),
        ("1,000 records", [1000.0], True),
    ],
)
def test_number_support(text: str, allowed: list[float], ok: bool) -> None:
    tokens = number_tokens(text)
    assert tokens and all(number_supported(t, allowed) for t in tokens) is ok


def test_numbers_that_are_not_quantities_are_ignored() -> None:
    text = "SS1/23 (lines 16-21) of m001_pd_scorecard.sas:16-21, `if age < 30`, 3 attempts, 2026-11-09 [E12]"
    assert number_tokens(text) == []
