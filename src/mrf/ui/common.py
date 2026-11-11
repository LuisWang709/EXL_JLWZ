"""Shared Streamlit pieces: connection, sign-in, status chips, the pipeline stepper. Owner: A4."""

from __future__ import annotations

import hmac
import html
import os
from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeVar

import streamlit as st

from mrf.ui.client import ApiClient, ApiError

T = TypeVar("T")

#: st.Page objects by name, filled by app.py, so pages can link to each other
PAGES: dict[str, Any] = {}

#: main path of a pipeline, in order (side states manual_review / failed are shown separately)
MAIN_STATES = [
    ("received", "Received"),
    ("classified", "Classified"),
    ("doc_drafting", "Drafting"),
    ("doc_rating", "Rating"),
    ("awaiting_doc_approval", "H1 approval"),
    ("rebuilding", "Rebuilding"),
    ("parity_passed", "Parity passed"),
    ("usability_run", "Usability run"),
    ("awaiting_signoff", "H2 sign-off"),
    ("deployed", "Deployed"),
    ("monitoring", "Monitoring"),
]
STATE_LABEL = dict(MAIN_STATES) | {"manual_review": "Manual review", "failed": "Failed"}
WAITING = {"awaiting_doc_approval", "awaiting_signoff", "manual_review"}
TONE = {
    "green": ("#d7f2df", "#135c2b"),
    "amber": ("#fdebc8", "#7a4b00"),
    "red": ("#f9d4d2", "#8a1c14"),
    "blue": ("#dce8f7", "#1d4e89"),
    "grey": ("#e6e8ee", "#4a5263"),
}

CSS = """
<style>
.mrf-chip{display:inline-block;padding:2px 10px;border-radius:999px;font-weight:600;font-size:.8rem;white-space:nowrap}
.mrf-steps{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 14px}
.mrf-step{padding:6px 10px;border-radius:8px;font-size:.8rem;border:1px solid #d5dae3;background:#fafbfd;color:#7a7f8c}
.mrf-step.done{background:#eef6f0;border-color:#b9dcc4;color:#135c2b}
.mrf-step.now{background:#1d4e89;border-color:#1d4e89;color:#fff;font-weight:600}
.mrf-step.wait{background:#fdebc8;border-color:#e8c27a;color:#7a4b00;font-weight:600}
.mrf-muted{color:#6b7280;font-size:.85rem}
</style>
"""


def chip(text: str, tone: str = "grey") -> str:
    bg, fg = TONE.get(tone, TONE["grey"])
    return f'<span class="mrf-chip" style="background:{bg};color:{fg}">{html.escape(text)}</span>'


def rag_chip(status: str | None) -> str:
    return chip(status.upper(), status) if status in {"green", "amber", "red"} else chip("NOT ASSESSED")


def state_chip(state: str) -> str:
    if state in {"failed"}:
        tone = "red"
    elif state in WAITING:
        tone = "amber"
    elif state in {"deployed", "monitoring"}:
        tone = "green"
    else:
        tone = "blue"
    return chip(STATE_LABEL.get(state, state), tone)


def stepper(state: str, history: list[dict[str, Any]] | None = None) -> str:
    """The main path as a row of steps: done / current (blue, or amber when waiting for a person) / to do."""
    visited = {h.get("to_state") for h in history or []}
    order = [s for s, _ in MAIN_STATES]
    current = order.index(state) if state in order else -1
    parts = []
    for i, (key, label) in enumerate(MAIN_STATES):
        if key == state:
            css = "wait" if key in WAITING else "now"
        elif (current >= 0 and i < current) or (current < 0 and key in visited):
            css = "done"
        else:
            css = ""
        parts.append(f'<div class="mrf-step {css}">{html.escape(label)}</div>')
    if state in {"manual_review", "failed"}:
        parts.append(
            f'<div class="mrf-step {"wait" if state == "manual_review" else "now"}">'
            f"{html.escape(STATE_LABEL[state])}</div>"
        )
    return '<div class="mrf-steps">' + "".join(parts) + "</div>"


def when(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def settings() -> tuple[str, str]:
    return os.environ.get("API_BASE_URL", "http://localhost:8000"), os.environ.get("MRF_API_KEY", "")


def signed_in() -> bool:
    """Deployed UI: the visitor must type the API key (the container already holds it, so the public URL alone
    is not enough). Locally without MRF_API_KEY: ask for URL and key."""
    if st.session_state.get("api") is not None:
        return True
    base_url, env_key = settings()
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("Model Risk Factory")
    st.caption("EXL Hackathon C04 · Team A — sign in with the team's API key")
    with st.form("signin"):
        url = base_url if env_key else st.text_input("API base URL", base_url)
        key = st.text_input("API key", type="password")
        operator = st.text_input("Your name (recorded on approvals)", value="")
        submitted = st.form_submit_button("Sign in", type="primary")
    if not submitted:
        return False
    if not key or not operator.strip():
        st.error("Enter the API key and your name.")
        return False
    if env_key and not hmac.compare_digest(key, env_key):
        st.error("Wrong API key.")
        return False
    client = ApiClient(url, key, operator=operator.strip())
    try:
        client.models()
    except ApiError as exc:
        st.error(f"Cannot use the API: {exc}")
        return False
    st.session_state["api"] = client
    st.rerun()
    return True


def api() -> ApiClient:
    client: ApiClient = st.session_state["api"]
    return client


def guard(fn: Callable[[], T], what: str) -> T | None:
    """Run an API call; show the error instead of a stack trace."""
    try:
        return fn()
    except ApiError as exc:
        if exc.status == 404 and exc.message == "Not Found":  # the route itself does not exist
            st.info(f"{what}: not available in this API version yet.")
        else:
            st.error(f"{what} failed — {exc}")
        return None


def go(name: str) -> None:
    st.switch_page(PAGES[name])


def link(name: str, label: str) -> None:
    st.page_link(PAGES[name], label=label, icon=":material/arrow_forward:")
