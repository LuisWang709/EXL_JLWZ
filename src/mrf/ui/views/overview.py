"""Overview: headline numbers, start a pipeline, every pipeline at a glance. Owner: A4."""

from __future__ import annotations

from functools import partial
from typing import Any

import pandas as pd
import streamlit as st

from mrf.ui.common import STATE_LABEL, WAITING, api, go, guard, link, when

DONE = {"monitoring", "deployed", "failed"}
DATA_TYPES = ["csv", "parquet", "xlsx", "json"]


def _model_names(models: list[dict[str, Any]]) -> dict[str, str]:
    return {m["model_id"]: m.get("name") or m["model_id"] for m in models}


def page() -> None:
    c = api()
    st.title("Overview")
    models = guard(c.models, "Model inventory") or []
    pipes = guard(c.pipelines, "Pipelines") or []
    pending = guard(lambda: c.reviews("pending"), "Review queue") or []
    open_alerts = guard(lambda: c.alerts(acknowledged=False), "Alerts")

    cols = st.columns(4)
    cols[0].metric("Models in inventory", len(models))
    cols[1].metric("Pipelines working", sum(1 for p in pipes if p["state"] not in DONE | WAITING))
    cols[2].metric("Waiting for a person", len(pending))
    cols[3].metric("Open monitoring alerts", open_alerts[1] if open_alerts else 0)

    with st.expander("Start a new model: upload SAS / R / Python code", expanded=not pipes):
        with st.form("start", clear_on_submit=True):
            name = st.text_input("Model name", placeholder="e.g. M001 PD scorecard")
            owner = st.text_input("Owner (optional)")
            files = st.file_uploader(
                "Model code, plus the legacy package if you have one (manifest.json, input_sample.csv, "
                "legacy_scores.csv, coefficients.json)",
                accept_multiple_files=True,
                type=["sas", "r", "py", "txt", "csv", "json"],
            )
            st.caption(
                "The rebuild is proven against the legacy scores in the package. Models named M001, M002 or M004 "
                "use the built-in demo packages."
            )
            dev = st.file_uploader("Development data (optional)", type=DATA_TYPES, key="ds_dev")
            oot = st.file_uploader("Hold-out / out-of-time data (optional)", type=DATA_TYPES, key="ds_oot")
            schema = st.selectbox("Data schema for the quality check", ["(none)", "german_credit_clean"])
            submitted = st.form_submit_button("Start pipeline", type="primary")
        if submitted:
            if not name.strip() or not files:
                st.error("Give the model a name and add at least one file.")
            else:
                uploads = [(f.name, f.getvalue(), f.type or "text/plain") for f in files]
                schema_name = None if schema == "(none)" else schema
                dataset_ids: list[str] = []
                failed = False
                for upload, role in ((dev, "development"), (oot, "out_of_time")):
                    if upload is None:
                        continue
                    content, fname = upload.getvalue(), upload.name
                    ds = guard(
                        partial(
                            c.upload_dataset,
                            fname,
                            content,
                            role=role,
                            schema_name=schema_name,
                            name=f"{name.strip()} {role}",
                        ),
                        f"Dataset {fname}",
                    )
                    if ds is None:
                        failed = True
                        break
                    dataset_ids.append(ds["dataset_id"])
                started = None
                if not failed:
                    started = guard(
                        lambda: c.start_pipeline(name.strip(), uploads, owner.strip() or None, dataset_ids), "Upload"
                    )
                if started:
                    st.session_state["pipeline_id"] = started["pipeline_id"]
                    st.success(f"Pipeline {started['pipeline_id']} started for model {started['model_id']}.")
                    link("pipelines", "Follow it on the Pipelines page")

    st.subheader("Pipelines")
    if not pipes:
        st.info("No pipeline yet. Upload a model above to start one.")
        return
    names = _model_names(models)
    rows = [
        {
            "pipeline": p["pipeline_id"],
            "model": names.get(p["model_id"], p["model_id"]),
            "state": STATE_LABEL.get(p["state"], p["state"]),
            "needs a person": "yes" if p["state"] in WAITING else "",
            "doc attempts": (p.get("attempts") or {}).get("doc", 0),
            "rebuild attempts": (p.get("attempts") or {}).get("parity", 0),
            "LLM calls": (p.get("usage") or {}).get("llm_calls", 0),
            "LLM cost (EUR)": (p.get("usage") or {}).get("cost_eur", 0.0),
            "updated": when(p.get("updated_at")),
        }
        for p in sorted(pipes, key=lambda p: p.get("updated_at") or "", reverse=True)
    ]
    event = st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={"LLM cost (EUR)": st.column_config.NumberColumn(format="%.4f")},
    )
    picked = event.selection.rows if event else []
    if picked:
        st.session_state["pipeline_id"] = rows[picked[0]]["pipeline"]
        go("pipelines")
    st.caption("Select a row to open the pipeline.")
