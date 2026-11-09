"""DocAgent: complete, evidenced M001 documentation; LLM statements are vetted against the evidence."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mrf.agents.doc.agent import DocAgent, EvidenceBook, _header
from mrf.llm import get_mock
from mrf.rating.checks import citations, claims
from mrf.rating.rubric import required_sections
from tests.unit.a3_helpers import m001_context, scored_m001_dataset


async def test_m001_draft_is_complete_and_every_statement_is_evidenced() -> None:
    ctx = await m001_context()
    doc = await DocAgent().draft(ctx)
    assert list(doc.sections) == required_sections()
    for sid, body in doc.sections.items():
        lines = claims(body)
        assert lines, sid
        for line in lines:
            marks = citations(line)
            assert marks and all(1 <= n <= len(doc.evidence) for n in marks), (sid, line)
    data = doc.sections["data"]
    for var in ("checking_status", "credit_history", "age_band", "duration_months", "log_amount"):
        assert f"| `{var}` |" in data
    assert "`default_flag`" in data and "A14" in data
    method = doc.sections["methodology"]
    assert "logit link" in method and "EVENT='1' and DESCENDING" in method and "`pd_legacy`" in method
    assert "fixed cut-offs (30, 45)" in doc.sections["assumptions_and_limitations"]
    assert "1e-06" in doc.sections["implementation"] and "0.25" in doc.sections["monitoring"]
    assert doc.content_md.startswith("# Model Documentation – M001 Retail PD scorecard")
    assert "## Evidence" in doc.content_md and doc.usage.llm_calls == 1
    refs = {e.ref for e in doc.evidence}
    assert "m001_pd_scorecard.sas:16-21" in refs and "config/pipeline.yaml#parity" in refs
    assert any(r.startswith("kb:ss1_23_principles_summary#") for r in refs)
    assert any(r.startswith("kb:sas_r_python_differences#") for r in refs)


async def test_code_evidence_quotes_are_the_raw_source_lines() -> None:
    ctx = await m001_context()
    doc = await DocAgent().draft(ctx)
    proc = next(e for e in doc.evidence if e.ref == "m001_pd_scorecard.sas:16-21")
    assert proc.quote is not None and proc.quote.startswith("proc logistic data=work.model_input")
    assert "class checking_status(ref='A14')" in proc.quote


async def test_llm_statements_are_vetted() -> None:
    ctx = await m001_context()
    agent = DocAgent()
    probe = await agent.draft(ctx)
    kb_id = next(f"E{i}" for i, e in enumerate(probe.evidence, 1) if e.ref.startswith("kb:ss1_23"))
    cfg_id = next(f"E{i}" for i, e in enumerate(probe.evidence, 1) if e.ref == "config/pipeline.yaml#monitoring")
    get_mock().register(
        "doc_writer",
        {
            "claims": [
                {
                    "section": "monitoring",
                    "text": "Amber starts at a PSI of 0.1 on any variable.",
                    "evidence": [cfg_id],
                },
                {"section": "performance", "text": "The model has a Gini of 0.87.", "evidence": [cfg_id]},
                {"section": "data", "text": "Applicant `income` is a key driver.", "evidence": [kb_id]},
                {"section": "data", "text": "Data is representative.", "evidence": ["E999"]},
                {"section": "appendix", "text": "Extra section.", "evidence": [kb_id]},
                {"section": "governance", "text": "Uncited statement.", "evidence": []},
            ]
        },
    )
    doc = await agent.draft(ctx)
    assert "Amber starts at a PSI of 0.1 on any variable." in doc.sections["monitoring"]
    text = "\n".join(doc.sections.values())
    for dropped in ("0.87", "`income`", "representative", "Extra section", "Uncited statement"):
        assert dropped not in text
    assert "appendix" not in doc.sections


async def test_feedback_reaches_the_prompt_and_attempt_is_kept() -> None:
    ctx = await m001_context(feedback=["Expand the limitations section"], attempt=2)
    doc = await DocAgent().draft(ctx)
    assert doc.attempt == 2
    prompt = get_mock().calls[-1].messages[-1].content
    assert "REVIEWER FEEDBACK" in prompt and "Expand the limitations section" in prompt


async def test_performance_uses_compute_metrics_when_a_scored_dataset_exists(tmp_path: Path) -> None:
    ds = await scored_m001_dataset(tmp_path)
    ctx = await m001_context(dataset_ids=[ds.dataset_id])
    doc = await DocAgent().draft(ctx)
    perf = doc.sections["performance"]
    assert re.search(r"AUC 0\.\d{3}, Gini 0\.\d{3}, KS 0\.\d{3}, Brier 0\.\d{4}", perf), perf
    metrics_ev = next(e for e in doc.evidence if e.quote and e.quote.startswith("compute_metrics(ds_m001_scored"))
    assert "n_records=300" in (metrics_ev.quote or "")
    # profile_data is A2's and not implemented yet: the draft says so instead of failing
    assert "Data profiling of ds_m001_scored was not available" in doc.sections["data"]


async def test_unparseable_source_is_mrf_2001() -> None:
    from mrf.contracts.models import ArtifactRef
    from mrf.core import MRFCode, MRFError
    from mrf.storage import get_blobs

    ctx = await m001_context()
    ref = await get_blobs().put_bytes("x/notes.r", b"\x00\x01", filename="notes.r")
    bad = ctx.model_copy(update={"source_files": [ArtifactRef(uri=ref.uri, filename="notes.r")]})
    with pytest.raises(MRFError) as err:
        await DocAgent().draft(bad)
    assert err.value.code == MRFCode.CODE_UNPARSEABLE


def test_evidence_book_dedupes_and_header_extraction() -> None:
    book = EvidenceBook()
    assert book.add("code", "a.sas:1-2", "x") == "E1" and book.add("code", "a.sas:1-2", "y") == "E1"
    assert book.add("kb", "kb:c#1") == "E2" and book.has("E2") and not book.has("E3")
    head = _header("/* M001 PD scorecard\n * Owner: Risk */\n%let x = 1;\n", "sas")
    assert head is not None and head[0] == "M001 PD scorecard Owner: Risk" and head[1:] == (1, 2)
    assert _header("# Behaviour score\nimport x\n", "python") == ("Behaviour score", 1, 1)
