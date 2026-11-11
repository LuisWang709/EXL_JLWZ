"""One pipeline: where it is, what it did, what it cost; refreshes itself while it is working. Owner: A4."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from mrf.ui.common import STATE_LABEL, WAITING, api, go, guard, state_chip, stepper, when

TERMINAL = {"monitoring", "failed"}


def _pick(pipes: list[dict[str, Any]], names: dict[str, str]) -> str | None:
    if not pipes:
        return None
    ids = [p["pipeline_id"] for p in sorted(pipes, key=lambda p: p.get("updated_at") or "", reverse=True)]
    by_id = {p["pipeline_id"]: p for p in pipes}
    current = st.session_state.get("pipeline_id")
    choice = st.selectbox(
        "Pipeline",
        ids,
        index=ids.index(current) if current in ids else 0,
        format_func=lambda i: f"{names.get(by_id[i]['model_id'], by_id[i]['model_id'])} · {i}",
    )
    st.session_state["pipeline_id"] = choice
    return str(choice)


def _detail(pipeline_id: str) -> None:
    c = api()
    p = guard(lambda: c.pipeline(pipeline_id), "Pipeline")
    if not p:
        return
    state = p["state"]
    st.markdown(stepper(state, p.get("history")), unsafe_allow_html=True)
    usage = p.get("usage") or {}
    cols = st.columns(5)
    cols[0].markdown(f"**State**<br>{state_chip(state)}", unsafe_allow_html=True)
    cols[1].metric("Current step", p.get("current_step") or "-")
    cols[2].metric("LLM calls", usage.get("llm_calls", 0))
    cols[3].metric("Tokens", f"{usage.get('prompt_tokens', 0) + usage.get('completion_tokens', 0):,}")
    cols[4].metric("LLM cost (EUR)", f"{usage.get('cost_eur', 0.0):.4f}")

    if state in WAITING:
        st.warning(f"Waiting for a person: {STATE_LABEL.get(state, state)}.")
        if st.button("Open the review queue", type="primary"):
            go("reviews")
    if p.get("last_error"):
        err = p["last_error"]
        st.error(f"Last error {err.get('code', '')}: {err.get('message', err)}")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("History")
        hist = [
            {
                "time": when(h.get("at")),
                "from": STATE_LABEL.get(h.get("from_state") or "", h.get("from_state") or ""),
                "to": STATE_LABEL.get(h["to_state"], h["to_state"]),
                "by": h.get("actor", ""),
                "note": h.get("note") or h.get("code") or "",
            }
            for h in reversed(p.get("history") or [])
        ]
        st.dataframe(pd.DataFrame(hist), hide_index=True, use_container_width=True)
    with right:
        st.subheader("Attempts")
        attempts = p.get("attempts") or {}
        if attempts:
            st.dataframe(
                pd.DataFrame([{"loop": k, "attempts": v} for k, v in attempts.items()]),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.caption("No retries.")
        st.subheader("Artifacts")
        st.json(p.get("artifacts") or {}, expanded=False)
        st.session_state["model_id"] = p["model_id"]
        if st.button("Open the model"):
            go("models")


def page() -> None:
    c = api()
    st.title("Pipelines")
    pipes = guard(c.pipelines, "Pipelines") or []
    names = {m["model_id"]: m.get("name") or m["model_id"] for m in (guard(c.models, "Models") or [])}
    pipeline_id = _pick(pipes, names)
    if pipeline_id is None:
        st.info("No pipeline yet. Start one from the Overview page.")
        return
    state = next((p["state"] for p in pipes if p["pipeline_id"] == pipeline_id), "")
    live = state not in TERMINAL | WAITING
    st.caption("Refreshes every 5 seconds while the pipeline is working." if live else "")
    st.fragment(_detail, run_every=5 if live else None)(pipeline_id)
