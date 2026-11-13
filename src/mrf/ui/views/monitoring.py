"""Monitoring: drift per batch, alerts, schedule, run the monitoring now, monitoring reports. Owner: A4."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from mrf.ui.common import api, flash, guard, rag_chip, track_job, when
from mrf.ui.common import live as live_view

SCORE_KEY = "__score__"
COLORS = {"green": "#2e8b57", "amber": "#d08c00", "red": "#c0392b"}


def psi_chart(
    metrics: list[dict[str, Any]], limits: dict[str, float], names: dict[str, str] | None = None,
) -> go.Figure:
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
    if names:
        fig.update_xaxes(tickmode="array", tickvals=labels, ticktext=[names.get(i, i) for i in labels])
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
    key = f"monitoring-job-{model_id}"
    st.session_state[key] = started["job_id"]
    st.session_state[key + "-active"] = True
    st.rerun()


def _job(model_id: str) -> bool:
    key = f"monitoring-job-{model_id}"
    job = track_job(key, "Monitoring job")
    if job and job.get("status") == "succeeded":
        result = job.get("result") or {}
        st.success(
            f"Done: {len(result.get('processed', []))} batch(es) processed, "
            f"{len(result.get('reports', []))} report(s) built."
        )
        for problem in result.get("rejected", []) + result.get("failed", []):
            st.warning(problem.get("message", problem))
    return bool(st.session_state.get(key + "-active"))


def _alerts(model_id: str) -> None:
    c = api()
    st.subheader("Alerts")
    filters, pages = st.columns([3, 1])
    state = filters.selectbox("Alert status", ["open", "acknowledged", "closed", "all"],
                              key=f"alert-filter-{model_id}")
    page = int(pages.number_input("Alerts page", min_value=1, step=1, key=f"alerts-page-{model_id}-{state}"))
    found = guard(lambda: c.alerts(model_id, status=None if state == "all" else state, page=page), "Alerts")
    if found is None:
        return
    alerts, total = found
    st.caption(f"Page {page} / {max(1, (total + 24) // 25)} · showing {len(alerts)} of {total} alerts. "
               "Acknowledgement records ownership; closing records a resolution.")
    if not alerts:
        st.info("No alerts on this page. Choose an earlier page or change the filter." if page > 1
                else "No alerts match this filter.")
        return
    st.dataframe(pd.DataFrame([{
        "raised": when(a.get("created_at")), "severity": a["severity"], "kind": a["kind"],
        "status": a["status"], "message": a["message"],
    } for a in alerts]), hide_index=True, use_container_width=True)
    by_id = {a["alert_id"]: a for a in alerts}
    selected = st.selectbox("Alert to review", list(by_id), key=f"alert-choice-{model_id}-{state}-{page}",
                           format_func=lambda i: f"{by_id[i]['severity'].upper()} · {by_id[i]['message']} · {i}")
    alert = by_id[selected]
    st.write(alert["message"])
    with st.expander("Alert evidence and handling history"):
        st.json(alert)
    with st.form(f"alert-action-{alert['alert_id']}"):
        resolution = st.text_area("Resolution / action taken", help="Required to close an alert.")
        ack, close = st.columns(2)
        acknowledged = ack.form_submit_button("Acknowledge alert", disabled=alert["acknowledged"])
        closed = close.form_submit_button("Close alert", disabled=alert["status"] == "closed")
    if closed and not resolution.strip():
        st.error("Describe the resolution before closing the alert.")
    elif acknowledged or closed:
        result = guard(lambda: c.close_alert(alert["alert_id"], resolution.strip()) if closed
                       else c.acknowledge_alert(alert["alert_id"]), "Update alert")
        if result:
            flash(f"Alert {result['status']} by {c.operator}. Historical metrics are unchanged.")
            st.rerun()


def _schedule(model_id: str, model: dict[str, Any], schedule: dict[str, Any]) -> None:
    st.subheader("Schedule")
    st.caption("The hourly cloud timer checks for new batches. This UTC cron controls periodic reports.")
    with st.form(f"schedule-{model_id}"):
        cron = st.text_input("Cron (UTC)", value=schedule["cron"], key=f"cron-{model_id}")
        enabled = st.toggle("Enabled", value=schedule["enabled"], key=f"schedule-enabled-{model_id}")
        saved = st.form_submit_button("Save schedule", disabled=model.get("lifecycle") != "production")
    if saved:
        result = guard(lambda: api().put_schedule(model_id, cron.strip(), enabled, schedule["report_types"]),
                       "Schedule")
        if result is not None:
            flash("Schedule saved. New-batch processing is " + ("enabled." if enabled else "paused."))
            st.rerun()


def _upload_batch(model_id: str) -> None:
    c = api()
    with st.expander("Upload a monitoring batch"):
        with st.form(f"upload-batch-{model_id}"):
            upload = st.file_uploader("Cleaned batch data", type=["csv", "parquet", "xlsx", "json"],
                                      key=f"batch-file-{model_id}")
            schema = st.selectbox("Batch quality schema", ["(none)", "german_credit_clean"],
                                  key=f"batch-schema-{model_id}")
            submit = st.form_submit_button("Upload monitoring batch")
        if submit:
            if upload is None:
                st.error("Choose a cleaned dataset first.")
            else:
                result = guard(lambda: c.upload_dataset(upload.name, upload.getvalue(), role="monitoring_batch",
                               model_id=model_id, schema_name=None if schema == "(none)" else schema), "Upload batch")
                if result:
                    flash(f"Batch {result['name']} uploaded ({result['row_count']} rows). "
                          "Process new batches to assess it.")
                    st.rerun()


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
    if st.button("Refresh monitoring", key="refresh-monitoring"):
        st.rerun()
    active = st.session_state.get(f"monitoring-job-{model_id}-active", False)
    fragment = live_view(_detail) if active else _detail
    st.fragment(fragment, run_every=3 if active else None)(model_id, by_id[model_id])


def _detail(model_id: str, model: dict[str, Any]) -> None:
    c = api()
    busy = _job(model_id)
    schedule = guard(lambda: c.schedule(model_id), "Monitoring configuration")
    if schedule is None:
        return
    baseline = schedule.get("baseline_dataset_id")
    if not baseline:
        st.warning("No monitoring baseline is registered. Complete dataset scoring and H2 before processing batches.")
    elif not schedule["enabled"]:
        st.info("Monitoring is paused. Enable the saved schedule to process new batches.")
    else:
        st.caption(f"Baseline: {baseline}. "
                   "Red drift returns the triggering batch to H2; it does not retrain the model.")
    _upload_batch(model_id)

    run_col, report_col, _ = st.columns([1, 1, 2])
    ready = bool(baseline and schedule["enabled"] and model.get("lifecycle") == "production")
    if run_col.button("Process new batches", use_container_width=True, disabled=busy or not ready):
        _run(model_id, report=False)
    if report_col.button("Build monitoring report now", type="primary", use_container_width=True,
                         disabled=busy or not baseline):
        _run(model_id, report=True)

    batches = guard(lambda: c.datasets(model_id, "monitoring_batch"), "Batches") or []
    names = {d["dataset_id"]: d["name"] for d in batches}
    metrics = guard(lambda: c.metrics(model_id), "Monitoring metrics") or []
    if metrics:
        latest = metrics[-1]
        st.caption(f"Latest: {names.get(latest['batch_id'], latest['batch_id'])} · {when(latest.get('at'))} UTC")
        if latest["status"] == "red" and not latest["psi"] and latest.get("gini") is None:
            st.warning("No score or drift result is available for this red batch. Review its data-quality alert "
                       "before interpreting it as model drift.")
        cols = st.columns(4)
        cols[0].markdown(f"**Latest batch**<br>{rag_chip(latest['status'])}", unsafe_allow_html=True)
        cols[1].metric("Batches", len(metrics))
        score_psi = latest["psi"].get(SCORE_KEY)
        cols[2].metric("Score PSI (latest)", "-" if score_psi is None else f"{score_psi:.3f}")
        cols[3].metric("Gini (latest)", "-" if latest.get("gini") is None else f"{latest['gini']:.3f}")
        st.plotly_chart(psi_chart(metrics, schedule["thresholds"], names), use_container_width=True)
        heat = feature_heatmap(metrics)
        if heat is not None:
            with st.expander("Feature drift by batch (CSI)"):
                st.plotly_chart(heat, use_container_width=True)
    else:
        st.info("No monitoring batch processed for this model yet.")

    if batches:
        completed = {m["batch_id"] for m in metrics}
        pending = [d for d in batches if d["dataset_id"] not in completed]
        st.caption(f"{len(pending)} pending batch(es). "
                   "Reprocessing an existing batch ID does not duplicate its alerts.")
    left, right = st.columns([3, 2])
    with left:
        _alerts(model_id)
    with right:
        _schedule(model_id, model, schedule)

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
