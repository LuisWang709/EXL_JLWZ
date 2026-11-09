#!/usr/bin/env python3
"""Convert a PDF (e.g. the official PRA SS1/23 text) into a knowledge-base markdown file. Owner: A3.

pypdf is not a project dependency (the container never needs it), so run with an ephemeral install:

    uv run --with pypdf python scripts/import_kb_pdf.py ~/Downloads/ss123.pdf --collection ss1_23 \
        --source "PRA SS1/23 - Model risk management principles for banks (official text)" \
        --url https://www.bankofengland.co.uk/... --licence "<terms you checked>"

Writes kb/<collection>/<stem>.md with front-matter and one ``## Page N`` section per page, so search results
cite the page in their locator. Check the licence before committing the output.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COLLECTIONS = ("ss1_23", "templates", "mapping")


def _clean(text: str) -> str:
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # re-join hyphenated line breaks
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--collection", choices=COLLECTIONS, required=True)
    ap.add_argument("--source", required=True, help="citation title shown in search results")
    ap.add_argument("--url", default="")
    ap.add_argument("--licence", required=True, help="terms that allow storing the text")
    ap.add_argument("--name", help="output file stem (default: PDF file name)")
    args = ap.parse_args()

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise SystemExit("pypdf missing - run with: uv run --with pypdf python scripts/import_kb_pdf.py ...") from exc

    reader = PdfReader(str(args.pdf))
    stem = re.sub(r"[^a-z0-9_]+", "_", (args.name or args.pdf.stem).lower()).strip("_")
    out = REPO_ROOT / "kb" / args.collection / f"{stem}.md"
    parts = [f"---\nsource: {args.source}\nurl: {args.url}\nlicence: {args.licence}\n---\n"]
    for i, page in enumerate(reader.pages, start=1):
        text = _clean(page.extract_text() or "")
        if text:
            parts.append(f"## Page {i}\n\n{text}\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {out.relative_to(REPO_ROOT)} ({len(reader.pages)} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
