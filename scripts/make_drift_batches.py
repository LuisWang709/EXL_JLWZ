#!/usr/bin/env python3
"""Synthetic monthly monitoring batches for the M001 demo (German Credit). Owner: A4.

Builds four batches from A2's cleaned German Credit data, each with a business story:

    month_01  random sample                                      -> expected green
    month_02  young applicants (age_band = 1) doubled            -> expected amber  (campus card campaign)
    month_03  negative balances (checking_status = A11) -> 60%,  -> expected red    (downturn: bigger loans,
              credit_amount +30% (still capped at 15000)                           more overdrawn accounts)
    month_04  a few rows with an unknown code / out-of-range      -> rejected by the pandera schema (MRF-3101)
              amount (upstream system changed)

Batches are drawn with *exact* category counts, so the drift does not depend on sampling luck.
The colour check uses A3's ``mrf.validation.psi/csi`` when available - this script never computes PSI itself.

Run (after ``uv run python scripts/preprocess_german_credit.py``):

    uv run python scripts/make_drift_batches.py
    uv run python scripts/make_drift_batches.py --rows 400 --seed 7 --out data/monitoring

Outputs ``data/monitoring/month_0N_<story>.parquet`` plus ``manifest.json`` (all git-ignored). Register them
through ``POST /api/v1/datasets`` with role=monitoring_batch, model_id=M001, schema_name=german_credit_clean.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
CLEAN = REPO_ROOT / "data" / "clean"
SCHEMA = "german_credit_clean"
AMOUNT_CAP = 15000.0  # A2's schema: credit_amount <= 15000
FEATURES = ["checking_status", "credit_history", "duration_months", "credit_amount", "log_amount", "age_band"]


def sample_with_shares(
    df: pd.DataFrame, column: str, shares: dict[Any, float], rows: int, rng: np.random.Generator
) -> pd.DataFrame:
    """Draw ``rows`` rows whose ``column`` has exactly the given category shares (with replacement)."""
    total = sum(shares.values())
    counts = {k: round(rows * v / total) for k, v in shares.items()}
    counts[max(counts, key=lambda k: counts[k])] += rows - sum(counts.values())  # fix rounding
    parts = []
    for value, n in counts.items():
        pool = df[df[column] == value]
        if n and pool.empty:
            raise ValueError(f"no rows with {column}={value!r} to sample from")
        if n:
            parts.append(pool.sample(n=n, replace=True, random_state=int(rng.integers(1 << 31))))
    return pd.concat(parts).sample(frac=1.0, random_state=int(rng.integers(1 << 31))).reset_index(drop=True)


def reference_shares(df: pd.DataFrame, column: str) -> dict[Any, float]:
    return {k: float(v) for k, v in df[column].value_counts(normalize=True).items()}


def with_share(base: dict[Any, float], key: Any, share: float) -> dict[Any, float]:
    """Set one category's share and rescale the others proportionally."""
    others = {k: v for k, v in base.items() if k != key}
    scale = (1.0 - share) / sum(others.values())
    return {key: share, **{k: v * scale for k, v in others.items()}}


def month_01(src: pd.DataFrame, rows: int, rng: np.random.Generator) -> pd.DataFrame:
    return src.sample(n=rows, replace=True, random_state=int(rng.integers(1 << 31))).reset_index(drop=True)


def month_02(src: pd.DataFrame, rows: int, rng: np.random.Generator) -> pd.DataFrame:
    base = reference_shares(src, "age_band")
    young = min(0.95, 2.0 * base.get(1, 0.15))
    return sample_with_shares(src, "age_band", with_share(base, 1, young), rows, rng)


def month_03(src: pd.DataFrame, rows: int, rng: np.random.Generator) -> pd.DataFrame:
    base = reference_shares(src, "checking_status")
    out = sample_with_shares(src, "checking_status", with_share(base, "A11", 0.60), rows, rng)
    out["credit_amount"] = (out["credit_amount"] * 1.3).clip(upper=AMOUNT_CAP).round(0)
    out["log_amount"] = np.log(out["credit_amount"].replace(0, np.nan))
    return out


def month_04(src: pd.DataFrame, rows: int, rng: np.random.Generator) -> pd.DataFrame:
    out = month_01(src, rows, rng)
    out.loc[out.index[:10], "checking_status"] = "A15"  # code that does not exist
    out.loc[out.index[10:15], "credit_amount"] = 20000.0  # above the schema cap
    return out


BATCHES: list[tuple[str, str, str, Callable[[pd.DataFrame, int, np.random.Generator], pd.DataFrame]]] = [
    ("month_01_normal", "green", "random sample, nothing changed", month_01),
    ("month_02_young_applicants", "amber", "campus card campaign: twice as many applicants under 25", month_02),
    ("month_03_downturn", "red", "downturn: 60% overdrawn accounts, loans 30% larger", month_03),
    ("month_04_upstream_change", "rejected", "upstream system change: unknown codes and amounts > 15000", month_04),
]


def build(source: pd.DataFrame, rows: int, seed: int) -> dict[str, tuple[str, str, pd.DataFrame]]:
    rng = np.random.default_rng(seed)
    return {name: (expected, story, fn(source, rows, rng)) for name, expected, story, fn in BATCHES}


def schema_ok(df: pd.DataFrame) -> bool:
    from mrf.data import validate

    try:
        validate(SCHEMA, df, lazy=True)
    except Exception:  # pandera SchemaErrors
        return False
    return True


def drift_summary(reference: pd.DataFrame, batch: pd.DataFrame) -> dict[str, float] | None:
    """CSI per feature via A3's library; None while mrf.validation is not implemented yet."""
    try:
        from mrf.validation import csi  # type: ignore[attr-defined]
    except ImportError:
        return None
    cols = [c for c in FEATURES if c in batch.columns]
    return {k: round(float(v), 4) for k, v in csi(reference[cols], batch[cols], columns=cols).items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=CLEAN / "german_credit_test.csv", help="rows to sample from")
    parser.add_argument("--reference", type=Path, default=CLEAN / "german_credit_train.csv", help="drift baseline")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "monitoring")
    parser.add_argument("--rows", type=int, default=400)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    for path in (args.source, args.reference):
        if not path.exists():
            parser.error(f"{path} not found - run scripts/get_data.py and scripts/preprocess_german_credit.py first")
    source, reference = pd.read_csv(args.source), pd.read_csv(args.reference)
    args.out.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, Any]] = []
    problems = 0
    for name, (expected, story, df) in build(source, args.rows, args.seed).items():
        path = args.out / f"{name}.parquet"
        df.to_parquet(path, index=False)
        ok = schema_ok(df)
        if ok != (expected != "rejected"):
            problems += 1
        csi_values = drift_summary(reference, df)
        manifest.append(
            {
                "file": path.name,
                "rows": len(df),
                "expected": expected,
                "story": story,
                "schema_ok": ok,
                "csi": csi_values,
            }
        )
        worst = max(csi_values.values()) if csi_values else None
        print(f"{name:28s} expected={expected:8s} schema_ok={ok!s:5s} max_csi={worst}")
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if manifest[0]["csi"] is None:
        print("note: mrf.validation.csi is not available yet (A3) - colours not verified, only the schema checks")
    print(f"wrote {len(manifest)} batches to {args.out}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
