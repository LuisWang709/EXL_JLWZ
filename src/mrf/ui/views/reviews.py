"""Human gates: H1 (documentation), H2 (validation sign-off), manual review. Owner: A4."""

from __future__ import annotations

from functools import partial
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from mrf.ui.common import api, chip, guard, when

GATE_TITLE = {
    "H1": "H1 · approve the model documentation",
    "H2": "H2 · validation sign-off",
    "manual": "Manual review · the system could not finish on its own",
}
RESUME_STATES = ["classified", "doc_drafting", "rebuilding", "usability_run"]


def _evidence(review: dict[str, Any]) -> None:
    c, payload, model_id = api(), review.get("payload") or {}, review["model_id"]
    doc_id = payload.get("doc_id")
    if doc_id:
        ratings = guard(lambda: c.ratings(model_id, doc_id), "Ratings") or []
        if ratings:
            last = ratings[-1]
            verdict = chip("PASSED", "green") if last.get("passed") else chip("FAILED", "red")
            st.markdown(
                f"Rating attempt {last.get('attempt')}: **{last.get('total', 0):.0f} / 100** "
                f"(rules {last.get('rule_score', 0):.0f} / 60, reviewer model {last.get('llm_score', 0):.0f} / 40) "
                f"{verdict}",
                unsafe_allow_html=True,
            )
            for comment in last.get("comments") or []:
                st.caption(f"• {comment}")
        with st.expander("Read the document"):
            page = guard(lambda: c.document_html(model_id, doc_id), "Document")
            if page:
                components.html(page, height=700, scrolling=True)
    for key, label in (("validation_report_id", "Validation report"), ("analysis_report_id", "Analysis report")):
        report_id = payload.get(key)
        if report_id:
            with st.expander(label):
                page = guard(partial(c.report_html, model_id, report_id), label)
                if page:
                    components.html(page, height=800, scrolling=True)
    if review["gate"] == "manual":
        st.json(payload, expanded=False)


def _decide(review: dict[str, Any]) -> None:
    c = api()
    rid = review["review_id"]
    with st.form(f"decide-{rid}"):
        comment = st.text_area("Comment (sent back to the agents on reject)", key=f"comment-{rid}")
        target = None
        if review["gate"] == "manual":
            target = st.selectbox(
                "Resume at (optional)", ["", *RESUME_STATES], key=f"target-{rid}", help="Default: the failed step"
            )
        approve, reject = st.columns(2)
        ok = approve.form_submit_button("Approve", type="primary", use_container_width=True)
        no = reject.form_submit_button("Reject", use_container_width=True)
    if ok or no:
        if no and not comment.strip():
            st.error("Say what must change when you reject.")
            return
        result = guard(
            lambda: c.decide(rid, "approve" if ok else "reject", comment.strip(), target or None), "Decision"
        )
        if result is not None:
            st.success(f"Recorded by {c.operator}. The pipeline continues in the background.")
            st.rerun()


def page() -> None:
    c = api()
    st.title("Review queue")
    gate = st.segmented_control("Gate", ["All", "H1", "H2", "manual"], default="All")
    pending = guard(lambda: c.reviews("pending", None if gate in (None, "All") else gate), "Review queue")
    if pending is None:
        return
    names = {m["model_id"]: m.get("name") or m["model_id"] for m in (guard(c.models, "Models") or [])}
    if not pending:
        st.success("Nothing is waiting for a person.")
    for review in sorted(pending, key=lambda r: r.get("created_at") or ""):
        title = (
            f"{GATE_TITLE.get(review['gate'], review['gate'])} — {names.get(review['model_id'], review['model_id'])}"
        )
        with st.container(border=True):
            st.markdown(f"**{title}**")
            st.caption(f"Raised {when(review.get('created_at'))} · pipeline {review['pipeline_id']}")
            st.write(review.get("reason", ""))
            _evidence(review)
            _decide(review)

    done = guard(lambda: c.reviews(None), "Decisions") or []
    decided = [r for r in done if r.get("status") != "pending"]
    if decided:
        st.subheader("Recent decisions")
        st.dataframe(
            [
                {
                    "decided": when(r.get("decided_at")),
                    "gate": r["gate"],
                    "model": names.get(r["model_id"], r["model_id"]),
                    "decision": r["status"],
                    "by": r.get("decided_by"),
                    "comment": r.get("comment"),
                }
                for r in sorted(decided, key=lambda r: r.get("decided_at") or "", reverse=True)[:20]
            ],
            hide_index=True,
            use_container_width=True,
        )
