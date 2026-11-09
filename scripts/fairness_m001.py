#!/usr/bin/env python3
"""M001 fairness by age band - the numbers block of docs/fairness_m001.md. Owner: A3.

    uv run python scripts/fairness_m001.py                 # 300-row fixture (tests/fixtures/m001), print only
    uv run python scripts/fairness_m001.py --write         # ... and replace the block in docs/fairness_m001.md
    uv run python scripts/fairness_m001.py --data data/clean/german_credit_test.csv \
        --scores runs/m001_oot_scores.csv --score-column pd_python --write    # full out-of-time data

``--data`` needs id, default_flag and age_band; ``--scores`` needs id and the score column (default: the
fixture's legacy scores). Age bands come from the M001 SAS code: 1 = under 30, 2 = 30-44, 3 = 45 and over.
Every number in the block is computed here with mrf.validation - nothing is typed by hand.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from mrf import validation as v

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "m001"
DOC = REPO_ROOT / "docs" / "fairness_m001.md"
BANDS = {"1": "under 30", "2": "30-44", "3": "45 and over"}
START, END = "<!-- numbers:start -->", "<!-- numbers:end -->"


def block(df: pd.DataFrame, score: str, source: str, coefficients: dict[str, float] | None) -> str:
    f = v.fairness(df["default_flag"], df[score], df["age_band"])
    lines = [
        START,
        f"Data: {source}; {f['n']} records; score `{score}`; overall AUC {v.auc(df['default_flag'], df[score]):.3f}, "
        f"Gini {v.gini(df['default_flag'], df[score]):.3f}. Decision threshold {f['threshold']:.4f} "
        "(declines as many applicants as the observed bad rate).",
        "",
        "| Age band | Ages | Records | Share | Bad rate | Approval rate | Adverse impact ratio | TPR (bads declined) "
        "| FPR (goods declined) | AUC within band |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for band, s in f["segments"].items():
        key = str(band).split(".")[0]
        auc = f"{s['auc']:.3f}" if s["auc"] is not None else "n/a"
        tpr = f"{s['tpr']:.1%}" if s["tpr"] is not None else "n/a"
        fpr = f"{s['fpr']:.1%}" if s["fpr"] is not None else "n/a"
        lines.append(
            f"| {key} | {BANDS.get(key, '?')} | {s['n']} | {s['share']:.1%} | {s['bad_rate']:.1%} | "
            f"{s['approval_rate']:.1%} | {s['adverse_impact_ratio']:.2f} | {tpr} | {fpr} | {auc} |"
        )
    lines += [
        "",
        f"- Disparate impact (lowest / highest approval rate): **{f['disparate_impact']:.2f}** "
        f"(reference band {f['reference_segment']}).",
        f"- Equal-opportunity gap (spread of TPR): {f['max_tpr_gap']:.1%}; spread of FPR: {f['max_fpr_gap']:.1%}.",
    ]
    if coefficients:
        b1, b2 = coefficients.get("age_band_1"), coefficients.get("age_band_2")
        if b1 is not None and b2 is not None:
            lines.append(
                f"- Model coefficients for age (log-odds against band 3, from coefficients.json): band 1 {b1:.3f}, "
                f"band 2 {b2:.3f}."
            )
    lines.append(END)
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=FIXTURE / "input_sample.csv")
    ap.add_argument("--scores", type=Path, default=FIXTURE / "legacy_scores.csv")
    ap.add_argument("--score-column", default="pd_legacy")
    ap.add_argument("--coefficients", type=Path, default=FIXTURE / "coefficients.json")
    ap.add_argument("--write", action="store_true", help=f"replace the numbers block in {DOC.relative_to(REPO_ROOT)}")
    args = ap.parse_args()

    data = pd.read_csv(args.data)
    scores = pd.read_csv(args.scores)[["id", args.score_column]]
    df = data.drop(columns=[args.score_column], errors="ignore").merge(scores, on="id", how="inner")
    if len(df) != len(data):
        print(f"warning: {len(data) - len(df)} rows of --data have no score and are excluded")
    coefficients = json.loads(args.coefficients.read_text()) if args.coefficients.exists() else None
    source = f"`{args.data.relative_to(REPO_ROOT) if args.data.is_relative_to(REPO_ROOT) else args.data.name}`"
    text = block(df, args.score_column, source, coefficients)
    print(text)
    if args.write:
        doc = DOC.read_text(encoding="utf-8")
        pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
        if not pattern.search(doc):
            raise SystemExit(f"markers {START} ... {END} not found in {DOC}")
        DOC.write_text(pattern.sub(lambda _: text, doc), encoding="utf-8")
        print(f"\nupdated {DOC.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
