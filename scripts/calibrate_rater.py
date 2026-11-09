#!/usr/bin/env python3
"""Rater calibration: one good M001 document vs deliberately broken variants. Owner: A3.

    uv run python scripts/calibrate_rater.py                     # offline (mock LLM) - what CI checks
    MRF_LLM_PROVIDER=openai OPENAI_BASE_URL=https://api.deepseek.com MRF_LLM_MODEL=deepseek-chat \
    OPENAI_API_KEY=... uv run python scripts/calibrate_rater.py --show-doc    # real LLM (run on your laptop)

Drafts the M001 documentation with the real DocAgent, rates it with DocRater, then rates broken copies (missing
sections, no evidence markers, an invented variable, an invented number, generic filler). Prints one row per
document and exits 1 if the good document fails or any broken one passes - the plan's calibration criterion.
Uses in-memory storage, so nothing is written to var/.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MRF_STORAGE_BACKEND", "memory")

REPO_ROOT = Path(__file__).resolve().parents[1]
SAS = REPO_ROOT / "tests" / "fixtures" / "classify" / "m001_pd_scorecard.sas"


async def run(show_doc: bool) -> int:
    from mrf import storage
    from mrf.agents.classify.agent import ClassifierAgent
    from mrf.agents.doc.agent import DocAgent
    from mrf.contracts.agents import StepContext
    from mrf.contracts.models import Document, ModelRecord
    from mrf.llm import get_llm
    from mrf.rating.rater import DocRater

    storage.set_repo(storage.MemoryRepository())
    storage.set_blobs(storage.LocalBlobStore(Path(tempfile.mkdtemp()) / "blobs"))
    ref = await storage.get_blobs().put_bytes("m001/" + SAS.name, SAS.read_bytes(), filename=SAS.name)
    model = ModelRecord(model_id="mdl_m001", name="M001 Retail PD scorecard", source_files=[ref])
    ctx = StepContext(pipeline_id="pl_calibration", model=model, source_files=[ref])
    model.classification = await ClassifierAgent().classify(ctx)
    await storage.get_repo().put("models", model.model_id, model)
    ctx = ctx.model_copy(update={"model": model})
    print(f"LLM provider: {get_llm().provider} / {get_llm().default_model}")

    good = await DocAgent().draft(ctx)
    if show_doc:
        print(good.content_md)

    def variant(name: str, sections: dict[str, str]) -> tuple[str, Document]:
        return name, good.model_copy(update={"doc_id": f"{good.doc_id}_{name}", "sections": sections}, deep=True)

    s = good.sections
    filler = "This section follows best practice and fully meets all regulatory expectations. [E1]"
    docs = [
        ("good", good),
        variant("missing_sections", {k: s[k] for k in ("purpose_and_use", "data")}),
        variant("no_evidence", {k: re.sub(r"\[E\d+\]", "", t) for k, t in s.items()}),
        variant("invented_variable", {**s, "data": s["data"] + "\n- `annual_income` is the main driver. [E1]"}),
        variant("invented_number", {**s, "performance": s["performance"] + "\n- Out-of-time Gini is 0.87. [E1]"}),
        variant("generic_filler", {k: f"- {filler}" for k in s}),
    ]
    rater = DocRater()
    failures = 0
    print(f"\n{'document':<18} {'rule':>6} {'llm':>6} {'total':>6} passed  veto / first comment")
    for name, doc in docs:
        r = await rater.rate(ctx, doc)
        expected = name == "good"
        ok = r.passed == expected
        failures += not ok
        note = ", ".join(r.veto_flags) or (r.comments[0][:70] if r.comments else "")
        print(
            f"{name:<18} {r.rule_score:6.1f} {r.llm_score:6.1f} {r.total:6.1f} {r.passed!s:<6}  {note}"
            + ("" if ok else "   <-- UNEXPECTED")
        )
    print("\ncalibration", "OK" if not failures else f"FAILED ({failures} unexpected)")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show-doc", action="store_true", help="print the good document")
    args = ap.parse_args()
    sys.path.insert(0, str(REPO_ROOT))
    return asyncio.run(run(args.show_doc))


if __name__ == "__main__":
    raise SystemExit(main())
