#!/usr/bin/env python3
"""Inspect the knowledge base behind ``search_kb``: chunk counts per file and the top hits for a query. Owner: A3.

    uv run python scripts/build_kb.py                                   # stats only
    uv run python scripts/build_kb.py "model documentation" --collection ss1_23 --top-k 3

The index itself is built in memory on first use (and rebuilt when a file changes), so this script is only a
sanity check after adding or editing sources.
"""

from __future__ import annotations

import argparse
from collections import Counter

from mrf.rag import COLLECTIONS, get_kb


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="?")
    ap.add_argument("--collection", choices=COLLECTIONS)
    ap.add_argument("--top-k", type=int, default=5)
    args = ap.parse_args()

    kb = get_kb()
    per_file = Counter(c.locator.split(" > ")[0] for c in kb.chunks)
    print(f"{len(kb.chunks)} chunks, {len(kb.vocab)} terms, backend={kb.backend}")
    for name, n in sorted(per_file.items()):
        print(f"  {n:4d}  {name}")
    if args.query:
        print(f"\nquery: {args.query!r}")
        for hit in kb.search(args.query, top_k=args.top_k, collection=args.collection):
            first = hit["text"].splitlines()[0][:90]
            print(f"  {hit['score']:.3f}  kb:{hit['chunk_id']:<45} {first}")
            print(f"         {hit['locator']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
