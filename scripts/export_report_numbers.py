#!/usr/bin/env python3
"""Export every number shown in stored reports with its source - the PPT sign-off checklist. Owner: A3.

    uv run python scripts/export_report_numbers.py                        # all analysis/validation reports
    uv run python scripts/export_report_numbers.py --model mdl_x --out signoff.csv

Reads the configured repository (local SQLite by default, Cosmos when MRF_STORAGE_BACKEND=cosmos). Each row is one
number as rendered in a report (``summary.numbers`` written by the report builder): report, key, text, source.
Copy PPT numbers from this file only, and tick each one off against it (plan: "PPT numbers signed off by A3").
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from pathlib import Path


async def run(model_id: str | None, out: Path | None) -> int:
    from mrf.contracts.models import Report
    from mrf.storage import Collections, get_repo

    where = {"type": ["analysis", "validation"], **({"model_id": model_id} if model_id else {})}
    page = await get_repo().find(Collections.REPORTS, Report, where=where, page_size=500)
    rows = [
        {
            "model_id": r.model_id,
            "report_id": r.report_id,
            "type": r.type,
            "created_at": r.created_at.isoformat(),
            "key": n.get("key"),
            "shown_as": n.get("text"),
            "source": n.get("source"),
            "signed_off": "",
        }
        for r in page.items
        for n in r.summary.get("numbers", [])
    ]
    fields = ["model_id", "report_id", "type", "created_at", "key", "shown_as", "source", "signed_off"]
    handle = out.open("w", newline="", encoding="utf-8") if out else sys.stdout
    writer = csv.DictWriter(handle, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    if out:
        handle.close()
        print(f"wrote {len(rows)} numbers from {len(page.items)} reports to {out}")
    await get_repo().close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", help="model_id to export (default: all)")
    ap.add_argument("--out", type=Path, help="csv file (default: stdout)")
    args = ap.parse_args()
    return asyncio.run(run(args.model, args.out))


if __name__ == "__main__":
    raise SystemExit(main())
