"""Build static review PDFs from versioned content. Requires the optional reportlab package.

    uv run --with reportlab python scripts/build_submission.py

These are review documents, not a claim of independent sign-off. PPTX export requires the presentation runtime.
"""

from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def paragraph(canvas: Any, text: str, x: float, y: float, width: float, style: Any) -> float:
    from reportlab.platypus import Paragraph

    block = Paragraph(escape(text).replace("\n", "<br/>"), style)
    _, height = block.wrap(width, 2000)
    if y - height < 35:
        raise ValueError(f"page content does not fit: {text[:60]}")
    block.drawOn(canvas, x, y - height)
    return y - height


def deck_pdf(target: Path) -> None:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Paragraph, Table, TableStyle

    deck = json.loads((ROOT / "docs/submission/deck.json").read_text("utf-8"))
    page = canvas.Canvas(str(target), pagesize=(960, 540))
    title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=30, leading=36, textColor=HexColor("#12314b"))
    lead = ParagraphStyle("lead", fontName="Helvetica", fontSize=22, leading=29, textColor=HexColor("#227b79"))
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=18, leading=25, textColor=HexColor("#23394a"))
    cell = ParagraphStyle("cell", parent=body, fontSize=15, leading=20)
    for index, slide in enumerate(deck["slides"], 1):
        page.setFillColor(HexColor("#f7f9fa"))
        page.rect(0, 0, 960, 540, stroke=0, fill=1)
        y = paragraph(page, slide["title"], 60, 485, 840, title) - 25
        y = paragraph(page, slide["lead"], 60, y, 840, lead) - 35
        if "table" in slide:
            rows = [[Paragraph(escape(v), cell) for v in row] for row in slide["table"]]
            table = Table(rows, colWidths=[840 / len(rows[0])] * len(rows[0]))
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), HexColor("#e1ecec")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, HexColor("#c7d4db")),
            ]))
            _, height = table.wrap(840, 400)
            if y - height < 55:
                raise ValueError(f"slide {index}: table does not fit")
            table.drawOn(page, 60, y - height)
        else:
            for point in slide["points"]:
                y = paragraph(page, point, 60, y, 840, body) - 20
        page.setFillColor(HexColor("#647582"))
        page.setFont("Helvetica", 9)
        page.drawString(60, 25, "Team A / Review copy / Acceptance evidence pending")
        page.drawRightString(900, 25, f"{index} / {len(deck['slides'])}")
        page.showPage()
    page.save()


def architecture_pdf(target: Path) -> None:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfgen import canvas

    page = canvas.Canvas(str(target), pagesize=(842, 595))
    title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=25, leading=30)
    label = ParagraphStyle("label", fontName="Helvetica", fontSize=12, leading=16)
    paragraph(page, "Model Risk Factory: component architecture", 38, 550, 760, title)
    paragraph(page, "REST + MCP in one API process. Exactly one API replica.", 38, 510, 760, label)

    def box(x: float, y: float, w: float, h: float, text: str, fill: str) -> None:
        page.setFillColor(HexColor(fill))
        page.setStrokeColor(HexColor("#507489"))
        page.rect(x, y, w, h, fill=1, stroke=1)
        paragraph(page, text, x + 12, y + h - 12, w - 24, label)

    def arrow(x: float, y: float, end_x: float, end_y: float) -> None:
        page.setStrokeColor(HexColor("#507489"))
        page.line(x, y, end_x, end_y)
        if end_x == x:
            page.line(end_x, end_y, end_x - 4, end_y + 7)
            page.line(end_x, end_y, end_x + 4, end_y + 7)
        else:
            page.line(end_x, end_y, end_x - 7, end_y + 4)
            page.line(end_x, end_y, end_x - 7, end_y - 4)

    box(38, 390, 170, 80, "Streamlit UI / REST clients\nUploads, reviews, reports", "#f1f5f8")
    box(245, 390, 250, 80, "FastAPI /api/v1\nGuards, async jobs, LangGraph\nH1 and H2 human review", "#e0eeee")
    box(535, 390, 268, 80, "Agent implementations\nIdentify, document, rate, rebuild,\nrun and report", "#e0eeee")
    arrow(208, 430, 245, 430)
    arrow(495, 430, 535, 430)
    box(38, 250, 170, 85, "Scheduled monitoring\nQuality, drift, alerts\nReturns red drift to validation", "#fff2db")
    box(245, 250, 250, 85,
        "Repository + artefacts\nSQLite / Cosmos\nAzure Files or private Blob\nMLflow experiment records", "#f1f5f8")
    box(535, 250, 268, 85, "MCP tools /mcp\nParse, profile, retrieve, score,\nparity and metrics", "#e0eeee")
    arrow(370, 390, 370, 335)
    arrow(669, 390, 669, 335)
    arrow(208, 290, 245, 290)
    box(535, 135, 268, 65,
        "LLM wrapper + knowledge base\nConfigured provider / local TF-IDF\nSandboxed scoring subprocess", "#f1f5f8")
    arrow(669, 250, 669, 200)
    paragraph(page, "Cloud: Azure Container Apps, managed identity, Key Vault and App Insights. "
              "The timer calls the API; computation stays in the API process.", 38, 195, 450, label)
    paragraph(page, "Review limits: offline tests use mock LLM. Python-reproduced legacy fixtures need independent "
              "SAS/R exports. Production acceptance and owner sign-off remain pending.", 38, 95, 760, label)
    page.setFont("Helvetica", 9)
    page.setFillColor(HexColor("#507489"))
    page.drawString(38, 25, "Sources: docs/architecture.md, infra/modules/aca.bicep, src/mrf/orchestrator/registry.py")
    page.save()


def rai_pdf(target: Path) -> None:
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfgen import canvas

    page = canvas.Canvas(str(target), pagesize=(595, 842))
    title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=20, leading=26)
    heading = ParagraphStyle("heading", fontName="Helvetica-Bold", fontSize=11, leading=15)
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=10.5, leading=14)
    text = (ROOT / "docs/submission/responsible-ai.md").read_text("utf-8")
    y = 800.0
    for block in text.strip().split("\n\n"):
        if block.startswith("# "):
            y = paragraph(page, block[2:], 42, y, 511, title) - 14
        elif block.startswith("## "):
            y = paragraph(page, block[3:], 42, y, 511, heading) - 6
        else:
            y = paragraph(page, " ".join(block.splitlines()), 42, y, 511, body) - 12
    page.save()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "output/pdf")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for filename, build in (
        ("model-risk-factory-review.pdf", deck_pdf),
        ("architecture.pdf", architecture_pdf),
        ("responsible-ai.pdf", rai_pdf),
    ):
        target = args.out / filename
        build(target)
        print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
