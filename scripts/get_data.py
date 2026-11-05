#!/usr/bin/env python3
"""Download public datasets for Challenge 04 and print licence notes.

Owner: A2 (data engineering / rebuild engineer).

Downloads the public credit-risk datasets used to build the "legacy" sample
models into ``data/raw/``. Raw data must NEVER be committed to git (see
``docs/data.md`` and ``.gitignore``); this script is the reproducible way to
re-obtain the data. Run with:

    uv run python scripts/get_data.py

Each dataset is downloaded only if it is not already present (idempotent).
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# Repo root is two levels above this file (scripts/ -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"

_CHUNK = 65536


@dataclass(frozen=True)
class Dataset:
    """One downloadable public dataset."""

    name: str
    url: str
    filename: str
    licence: str
    source: str


# --- Catalogue -----------------------------------------------------------
# Only UCI datasets are listed here because they need no login. Kaggle
# datasets (Give Me Some Credit, ULB Credit Card Fraud) require a Kaggle
# account and agreement to competition rules, so they are documented but
# downloaded manually -- see data/README.md.
DATASETS: list[Dataset] = [
    Dataset(
        name="Statlog German Credit",
        url=(
            "https://archive.ics.uci.edu/ml/machine-learning-databases/"
            "statlog/german/german.data"
        ),
        filename="german_credit.data",
        licence="Public / for academic research (UCI ML Repository).",
        source="UCI ML Repository",
    ),
    Dataset(
        name="Statlog German Credit (codebook)",
        url=(
            "https://archive.ics.uci.edu/ml/machine-learning-databases/"
            "statlog/german/german.doc"
        ),
        filename="german_credit.doc",
        licence="Public / for academic research (UCI ML Repository).",
        source="UCI ML Repository",
    ),
    Dataset(
        name="Default of Credit Card Clients (Taiwan)",
        url=(
            "https://archive.ics.uci.edu/ml/machine-learning-databases/"
            "00350/default%20of%20credit%20card%20clients.xls"
        ),
        filename="taiwan_credit_default.xls",
        licence="Public / for academic research (UCI ML Repository).",
        source="UCI ML Repository",
    ),
]


def _download(ds: Dataset) -> Path:
    """Download a single dataset into data/raw, skipping if present."""
    dest = RAW_DIR / ds.filename
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[skip] {ds.name}: {dest.name} already present")
        return dest

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[get ] {ds.name}")
    print(f"       {ds.url}")
    try:
        req = urllib.request.Request(ds.url, headers={"User-Agent": "Mozilla/5.0"})  # noqa: S310
        with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:  # noqa: S310
            while True:
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
    except Exception as exc:
        print(f"[fail] {ds.name}: {exc}", file=sys.stderr)
        dest.unlink(missing_ok=True)
        return dest

    size = dest.stat().st_size
    print(f"[ ok ] {ds.name}: {dest.name} ({size} bytes)")
    return dest


def _print_licences() -> None:
    """Print the licence note for each dataset in the catalogue."""
    print("\nLicence notes (keep these in the submission README):")
    for ds in DATASETS:
        print(f"  - {ds.name} ({ds.source}): {ds.licence}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-licence",
        action="store_true",
        help="do not print licence notes",
    )
    args = parser.parse_args(argv)

    print(f"Raw data directory: {RAW_DIR}")
    for ds in DATASETS:
        _download(ds)

    if not args.skip_licence:
        _print_licences()

    print("\nDone. Remaining Kaggle datasets (GMSC, ULB fraud) need manual download.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
