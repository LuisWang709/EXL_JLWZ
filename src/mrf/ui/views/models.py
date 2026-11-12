"""Model inventory and everything produced for one model. Owner: A4."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from mrf.ui.common import api, guard, rag_chip, track_job, when


def _inventory(models: list[dict[str, Any]]) -> None:
    rows = []
    for m in models:
        cls = m.get("classification") or {}
        rows.append(
            {
                "model": m.get("name"),
                "id": m["model_id"],
                "language": cls.get("language"),
                "algorithm": cls.get("algorithm"),
                "purpose": cls.get("purpose"),
                "confidence": cls.get("confidence"),
                "needs review": "yes" if cls.get("needs_review") else "",
                "lifecycle": m.get("lifecycle"),
                "updated": when(m.get("updated_at")),
            }
        )
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        column_config={"confidence": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="%.2f")},
    )


def _classification(model: dict[str, Any]) -> None:
    cls = model.get("classification")
    if not cls:
        st.info("Not classified yet.")
        return
    facts = {k: v for k, v in cls.items() if not isinstance(v, list | dict) and k != "evidence"}
    st.dataframe(pd.DataFrame([{"field": k, "value": str(v)} for k, v in facts.items()]), hide_index=True)
    for key in ("features", "procedures"):
        if cls.get(key):
            st.markdown(f"**{key.capitalize()}**: " + ", ".join(f"`{f}`" for f in cls[key]))
    if cls.get("evidence"):
        with st.expander("Evidence"):
            st.dataframe(pd.DataFrame(cls["evidence"]), hide_index=True, use_container_width=True)


def _documents(model_id: str) -> None:
    c = api()
    docs = guard(lambda: c.documents(model_id), "Documents") or []
    if not docs:
        st.info("No documentation yet.")
        return
    doc = st.selectbox(
        "Version",
        docs,
        format_func=lambda d: f"attempt {d.get('attempt')} · {d.get('status')} · {when(d.get('created_at'))}",
    )
    ratings = guard(lambda: c.ratings(model_id, doc["doc_id"]), "Ratings") or []
    if ratings:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "attempt": r.get("attempt"),
                        "total / 100": r.get("total"),
                        "rules / 60": r.get("rule_score"),
                        "reviewer / 40": r.get("llm_score"),
                        "passed": r.get("passed"),
                        "vetoes": ", ".join(r.get("veto_flags") or []),
                    }
                    for r in ratings
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
    page = guard(lambda: c.document_html(model_id, doc["doc_id"]), "Document")
    if page:
        components.html(page, height=750, scrolling=True)


def _rebuilds(model_id: str) -> None:
    active = st.session_state.get(f"rebuild-job-{model_id}-active", False)
    st.fragment(_rebuild_detail, run_every=3 if active else None)(model_id)


def _rebuild_detail(model_id: str) -> None:
    c = api()
    job_key = f"rebuild-job-{model_id}"
    job = track_job(job_key, "Rebuild")
    busy = bool(st.session_state.get(job_key + "-active"))
    with st.form(f"start-rebuild-{model_id}"):
        fixture_id = st.text_input(
            "Parity fixture ID (optional)",
            help="Leave empty to use the uploaded legacy package or a matching built-in demo fixture.",
        )
        submitted = st.form_submit_button("Start Python rebuild", type="primary", disabled=busy)
    st.caption(
        "Standalone rebuild and parity test. This does not approve H1/H2 or advance the pipeline. "
        "Raw training data alone cannot prove parity: a legacy package must include reference scores."
    )
    if submitted:
        started = guard(lambda: c.start_rebuild(model_id, fixture_id.strip() or None), "Start rebuild")
        if started:
            st.session_state[job_key] = started["job_id"]
            st.session_state[job_key + "-active"] = True
            st.rerun()
    if job:
        if job.get("status") == "succeeded":
            result = job.get("result") or {}
            if result.get("passed"):
                st.success("Rebuild job completed. The parity result and any certificate are listed below.")
            else:
                st.warning("Rebuild attempts finished without matching the reference scores. See the feedback below.")
    if st.button("Refresh rebuild status", key=f"refresh-rebuild-{model_id}"):
        st.rerun()
    rebuilds = guard(lambda: c.rebuilds(model_id), "Rebuilds") or []
    if not rebuilds:
        st.info("No rebuild attempt yet. Approve H1 in the Review queue or start a standalone rebuild above.")
        return
    rows = []
    for r in rebuilds:
        parity = r.get("parity") or {}
        rows.append(
            {
                "attempt": r.get("attempt"),
                "status": r.get("status"),
                "parity passed": None if (parity.get("detail") or {}).get("skipped") else parity.get("passed"),
                "records": parity.get("n_records"),
                "mismatches": parity.get("n_mismatches"),
                "max abs diff": parity.get("max_abs_diff"),
                "tolerance": parity.get("tolerance"),
                "written by": {"llm": "LLM", "template": "transcription", "none": "not needed"}.get(
                    str((parity.get("detail") or {}).get("generator")), ""
                ),
                "code": (r.get("code") or {}).get("filename", ""),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    latest = rebuilds[0]
    skipped = ((latest.get("parity") or {}).get("detail") or {}).get("skipped")
    if skipped:
        st.info(f"No translation: {skipped}.")
    for item in (latest.get("feedback") or [])[:5]:
        st.caption(f"• {item}")
    if latest.get("certificate"):
        with st.expander("Parity certificate", expanded=True):
            page = guard(lambda: c.rebuild_certificate(model_id, latest["rebuild_id"]), "Certificate")
            if page:
                components.html(page, height=620, scrolling=True)
    if latest.get("code"):
        with st.expander("Source Python code" if skipped else "Rebuilt Python code"):
            code = guard(lambda: c.rebuild_code(model_id, latest["rebuild_id"]), "Code")
            if code:
                st.code(code, language="python")
                st.download_button("Download Python code", code, file_name="model.py", mime="text/x-python")


def _runs(model_id: str) -> None:
    c = api()
    runs = guard(lambda: c.runs(model_id), "Runs") or []
    if not runs:
        st.info("No model run yet.")
        return
    rows = []
    for r in runs:
        metrics = {k: v for k, v in (r.get("metrics") or {}).items() if isinstance(v, int | float)}
        rows.append(
            {
                "kind": r.get("kind"),
                "dataset": r.get("dataset_id"),
                "status": r.get("status"),
                "created": when(r.get("created_at")),
                **metrics,
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def _reports(model_id: str) -> None:
    c = api()
    reports = guard(lambda: c.reports(model_id), "Reports") or []
    if not reports:
        st.info("No report yet.")
        return
    report = st.selectbox(
        "Report",
        reports,
        format_func=lambda r: f"{r['type']} · {r.get('rag_status') or 'n/a'} · {when(r.get('created_at'))}",
    )
    st.markdown(f"Overall: {rag_chip(report.get('rag_status'))}", unsafe_allow_html=True)
    summary = report.get("summary") or {}
    for line in summary.get("findings") or []:
        st.caption(f"• {line}")
    page = guard(lambda: c.report_html(model_id, report["report_id"]), "Report")
    if page:
        st.download_button("Download HTML", page, file_name=f"{report['report_id']}.html", mime="text/html")
        components.html(page, height=900, scrolling=True)


def page() -> None:
    c = api()
    st.title("Models")
    models = guard(c.models, "Model inventory") or []
    if not models:
        st.info("The inventory is empty. Start a pipeline from the Overview page.")
        return
    _inventory(models)
    ids = [m["model_id"] for m in models]
    by_id = {m["model_id"]: m for m in models}
    current = st.session_state.get("model_id")
    model_id = st.selectbox(
        "Model",
        ids,
        index=ids.index(current) if current in ids else 0,
        format_func=lambda i: f"{by_id[i].get('name')} · {i}",
    )
    st.session_state["model_id"] = model_id
    if st.button("Refresh model", key="refresh-model"):
        st.rerun()
    tabs = st.tabs(["Classification", "Documentation", "Python rebuild", "Runs", "Reports"])
    with tabs[0]:
        _classification(by_id[model_id])
    with tabs[1]:
        _documents(model_id)
    with tabs[2]:
        _rebuilds(model_id)
    with tabs[3]:
        _runs(model_id)
    with tabs[4]:
        _reports(model_id)
