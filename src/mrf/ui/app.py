"""Streamlit entry point. Owner: A4.

    uv run --extra ui streamlit run src/mrf/ui/app.py

Environment: ``API_BASE_URL`` (default http://localhost:8000) and, in Azure, ``MRF_API_KEY`` (from Key Vault).
With ``MRF_API_KEY`` set, visitors must type that key to sign in; the UI then calls the API with it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st

from mrf.ui import common
from mrf.ui.views import models, monitoring, overview, pipelines, reviews

st.set_page_config(page_title="Model Risk Factory", page_icon=":material/fact_check:", layout="wide")

if common.signed_in():
    st.markdown(common.CSS, unsafe_allow_html=True)
    common.PAGES.update(
        overview=st.Page(
            overview.page, title="Overview", icon=":material/dashboard:", url_path="overview", default=True
        ),
        pipelines=st.Page(pipelines.page, title="Pipelines", icon=":material/account_tree:", url_path="pipelines"),
        reviews=st.Page(reviews.page, title="Review queue", icon=":material/task_alt:", url_path="reviews"),
        models=st.Page(models.page, title="Models", icon=":material/inventory_2:", url_path="models"),
        monitoring=st.Page(monitoring.page, title="Monitoring", icon=":material/monitoring:", url_path="monitoring"),
    )
    nav = st.navigation(list(common.PAGES.values()))
    client = common.api()
    # the GETs this page makes anyway, fetched in parallel so its own calls are served from the client cache
    prefetch: dict[str, list[Callable[[], Any]]] = {
        "Overview": [
            client.models,
            client.pipelines,
            lambda: client.reviews("pending"),
            lambda: client.alerts(acknowledged=False),
            client.datasets,
        ],
        "Pipelines": [client.pipelines, client.models],
        "Review queue": [lambda: client.reviews("pending"), lambda: client.reviews(None), client.models],
        "Models": [client.models],
        "Monitoring": [client.models],
    }
    client.warm([client.health, *prefetch.get(nav.title, [])])
    with st.sidebar:
        st.caption(f"Signed in as **{client.operator}**")
        st.caption(f"API: {client.base_url}")
        try:
            ready = client.health()
            checks = ready.get("checks", {})
            st.caption("Health: " + " · ".join(f"{k} {'✓' if v == 'ok' else '✗'}" for k, v in checks.items()))
        except common.ApiError as exc:
            st.caption(f"Health: {exc}")
        if st.button("Sign out"):
            client.close()
            st.session_state.clear()
            st.rerun()
    common.show_flash()
    nav.run()
