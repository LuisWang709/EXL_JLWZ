"""Monitoring: drift per batch, alerts, schedule, run the monitoring now, monitoring reports. Owner: A4."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from mrf.ui.common import api, guard, rag_chip, when

SCORE_KEY = "__score__"
COLORS = {"green": "#2e8b57", "amber": "#d08c00", "red": "#c0392b"}


def thresholds() -> dict[str, float]:
    """config/pipeline.yaml (shipped in the UI image); defaults if it cannot be read."""
    try:
        from mrf.config import get_policy

        mon = get_policy()["monitoring"]
        return {"psi_amber": float(mon["psi_amber"]), "psi_red": float(mon["psi_red"])}
    except Exception:
        return {"psi_amber": 0.10, "psi_red": 0.25}


def psi_chart(metrics: list[dict[str, Any]], limits: dict[str, float]) -> go.Figure:
    labels = [m["batch_id"] for m in metrics]
    score = [m["psi"].get(SCORE_KEY) for m in metrics]
    worst = [max((v for k, v in m["psi"].items() if k != SCORE_KEY), default=None) for m in metrics]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=labels, y=score, name="score PSI", mode="lines+markers", line={"color": "#1d4e89"}))
    fig.add_trace(
        go.Scatter(
            x=labels,
            y=worst,
            name="largest feature PSI",
            mode="lines+markers",
            line={"color": "#7a7f8c", "dash": "dot"},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=labels,
            y=[0] * len(labels),
            mode="markers",
            marker={"symbol": "square", "size": 12, "color": [COLORS.get(m["status"], "#999") for m in metrics]},
            name="batch status",
            hovertext=[m["status"] for m in metrics],
        )
    )
    for key, color in (("psi_amber", COLORS["amber"]), ("psi_red", COLORS["red"])):
        fig.add_hline(y=limits[key], line_dash="dash", line_color=color, annotation_text=key.replace("psi_", ""))
    fig.update_layout(
        height=340, margin={"l": 10, "r": 10, "t": 30, "b": 10}, yaxis_title="PSI", legend_orientation="h"
    )
    return fig


def feature_heatmap(metrics: list[dict[str, Any]]) -> go.Figure | None:
    features = sorted({k for m in metrics for k in m["psi"] if k != SCORE_KEY})
    if not features:
        return None
    z = [[m["psi"].get(f) for m in metrics] for f in features]
    fig = go.Figure(
        go.Heatmap(z=z, x=[m["batch_id"] for m in metrics], y=features, colorscale="YlOrRd", colorbar={"title": "PSI"})
    )
    fig.update_layout(height=max(260, 22 * len(features)), margin={"l": 10, "r": 10, "t": 10, "b": 10})
    return fig


def _run(model_id: str, report: bool) -> None:
    c = api()
    started = guard(lambda: c.monitoring_run(model_id, report=report), "Monitoring run")
    if not started:
        return
    with st.spinner("Processing new batches" + (" and building the report" if report else "") + "..."):
        job = c.wait_job(started["job_id"], timeout=180)
    if job.get("status") == "succeeded":
        result = job.get("result") or {}
        st.success(
            f"Done: {len(result.get('processed', []))} batch(es) processed, "
            f"{len(result.get('reports', []))} report(s) built."
        )
        for problem in result.get("rejected", []) + result.get("failed", []):
            st.warning(problem.get("message", problem))
    else:
        st.error(f"Monitoring job {job.get('status')}: {(job.get('error') or {}).get('message', '')}")


def page() -> None:
    c = api()
    st.title("Monitoring")
    models = guard(c.models, "Model inventory") or []
    if not models:
        st.info("No model yet.")
        return
    by_id = {m["model_id"]: m for m in models}
    ids = sorted(by_id, key=lambda i: (by_id[i].get("lifecycle") != "production", by_id[i].get("name") or i))
    current = st.session_state.get("model_id")
    model_id = st.selectbox(
        "Model",
        ids,
        index=ids.index(current) if current in ids else 0,
        format_func=lambda i: f"{by_id[i].get('name')} · {by_id[i].get('lifecycle')}",
    )
    st.session_state["model_id"] = model_id

    run_col, report_col, _ = st.columns([1, 1, 2])
    if run_col.button("Process new batches", use_container_width=True):
        _run(model_id, report=False)
    if report_col.button("Build monitoring report now", type="primary", use_container_width=True):
        _run(model_id, report=True)

    metrics = guard(lambda: c.metrics(model_id), "Monitoring metrics") or []
    if metrics:
        latest = metrics[-1]
        cols = st.columns(4)
        cols[0].markdown(f"**Latest batch**<br>{rag_chip(latest['status'])}", unsafe_allow_html=True)
        cols[1].metric("Batches", len(metrics))
        score_psi = latest["psi"].get(SCORE_KEY)
        cols[2].metric("Score PSI (latest)", "-" if score_psi is None else f"{score_psi:.3f}")
        cols[3].metric("Gini (latest)", "-" if latest.get("gini") is None else f"{latest['gini']:.3f}")
        st.plotly_chart(psi_chart(metrics, thresholds()), use_container_width=True)
        heat = feature_heatmap(metrics)
        if heat is not None:
            with st.expander("Feature drift by batch (CSI)"):
                st.plotly_chart(heat, use_container_width=True)
    else:
        st.info("No monitoring batch processed for this model yet.")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Alerts")
        alerts = guard(lambda: c.alerts(model_id), "Alerts")
        if alerts and alerts[0]:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "raised": when(a.get("created_at")),
                            "severity": a["severity"],
                            "kind": a["kind"],
                            "message": a["message"],
                            "acknowledged": a.get("acknowledged"),
                        }
                        for a in alerts[0]
                    ]
                ),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.caption("No alerts.")
    with right:
        st.subheader("Schedule")
        model = by_id[model_id]
        with st.form("schedule"):
            cron = st.text_input("Cron (UTC)", value="0 6 * * 1", help="minute hour day-of-month month day-of-week")
            enabled = st.toggle("Enabled", value=True)
            saved = st.form_submit_button("Save schedule")
        if saved:
            if model.get("lifecycle") != "production":
                st.warning("Schedules apply to deployed models only (lifecycle 'production').")
            elif guard(lambda: c.put_schedule(model_id, cron.strip(), enabled), "Schedule") is not None:
                st.success("Schedule saved. The hourly timer builds a report when it is due or new batches arrive.")

    st.subheader("Monitoring reports")
    reports = guard(lambda: c.reports(model_id, "monitoring"), "Reports") or []
    if not reports:
        st.caption("No monitoring report yet — use “Build monitoring report now”.")
        return
    report = st.selectbox(
        "Report",
        reports,
        format_func=lambda r: f"{when(r.get('created_at'))} · {r.get('rag_status') or 'no batches'}",
    )
    page_html = guard(lambda: c.report_html(model_id, report["report_id"]), "Report")
    if page_html:
        st.download_button("Download HTML", page_html, file_name=f"{report['report_id']}.html", mime="text/html")
        components.html(page_html, height=1000, scrolling=True)
