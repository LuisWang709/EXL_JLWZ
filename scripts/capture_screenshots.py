#!/usr/bin/env python3
"""Capture UI screenshots of a running demo (API + Streamlit) for the slides and the tutorial.

    uv run --with playwright python scripts/capture_screenshots.py \\
        --ui http://localhost:8501 --out local/doc/screenshots

Uses the installed Microsoft Edge (``--channel msedge``; no browser download). The API key is read from
``MRF_UI_KEY`` (or ``MRF_API_KEY``). The session lives in the page, so navigation is by clicking the sidebar.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

SETTLE_MS = 2500


def settle(page: Page, extra: int = 0) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(SETTLE_MS + extra)


def shot(page: Page, out: Path, name: str, height: int = 1500) -> None:
    page.set_viewport_size({"width": 1500, "height": height})
    page.wait_for_timeout(700)
    page.screenshot(path=str(out / f"{name}.png"))
    print("saved", name)


def nav(page: Page, title: str) -> None:
    page.get_by_test_id("stSidebarNav").get_by_text(title, exact=True).click()
    settle(page)


def tab(page: Page, title: str) -> None:
    page.get_by_role("tab", name=title).click()
    settle(page, 800)


def choose(page: Page, index: int, text: str) -> bool:
    """Pick the option containing ``text`` in the index-th select box of the main area."""
    boxes = page.get_by_test_id("stMain").get_by_test_id("stSelectbox")
    if boxes.count() <= index:
        return False
    boxes.nth(index).click()
    option = page.get_by_role("option").filter(has_text=text)
    if option.count() == 0:
        page.keyboard.press("Escape")
        return False
    option.first.click()
    settle(page)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ui", default="http://localhost:8501")
    parser.add_argument("--out", default="local/doc/screenshots")
    parser.add_argument("--operator", default="independent.validator")
    parser.add_argument("--channel", default="msedge")
    args = parser.parse_args()
    key = os.environ.get("MRF_UI_KEY") or os.environ.get("MRF_API_KEY") or ""
    if not key:
        print("set MRF_UI_KEY (or MRF_API_KEY)", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=args.channel, headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 900}, device_scale_factor=1.5)
        page.goto(args.ui)
        settle(page)
        shot(page, out, "01_sign_in", 700)
        page.get_by_label("API key").fill(key)
        page.get_by_label("Your name (recorded on approvals)").fill(args.operator)
        page.get_by_role("button", name="Sign in").click()
        settle(page, 1500)
        shot(page, out, "02_overview", 1250)

        nav(page, "Pipelines")
        choose(page, 0, "M001")
        shot(page, out, "03_pipeline_m001", 1500)
        if choose(page, 0, "M002"):
            shot(page, out, "04_pipeline_m002", 1500)

        nav(page, "Review queue")
        shot(page, out, "05_review_queue", 1700)

        nav(page, "Models")
        choose(page, 0, "M001")
        shot(page, out, "06_model_classification", 1100)
        for name, title, height in (
            ("07_model_documentation", "Documentation", 1900),
            ("08_model_rebuild", "Python rebuild", 1900),
            ("09_model_runs", "Runs", 1000),
            ("10_model_reports", "Reports", 2100),
        ):
            tab(page, title)
            shot(page, out, name, height)

        nav(page, "Monitoring")
        choose(page, 0, "M001")
        shot(page, out, "11_monitoring", 2300)
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
