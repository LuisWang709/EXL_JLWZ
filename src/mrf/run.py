"""CLI: ``uv run python -m mrf.run --model M001`` runs one pipeline end to end (A1, 11/3).

Uses the in-process job executor and mock LLM unless MRF_LLM_PROVIDER says otherwise.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mrf.run", description="Run one MRF pipeline locally")
    parser.add_argument("--model", required=True, help="legacy model id, e.g. M001 (models/legacy/M001_*)")
    parser.add_argument("--dataset", action="append", default=[], help="dataset id or path (repeatable)")
    parser.add_argument("--auto-approve", action="store_true", help="auto-approve H1/H2 (local demo only)")
    args = parser.parse_args(argv)
    print(f"[mrf] pipeline runner not implemented yet (model={args.model}) - A1 task 11/3", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
