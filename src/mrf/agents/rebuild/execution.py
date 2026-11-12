"""Run a rebuilt scoring module on a table, inside the sandbox (``run_sandbox`` MCP tool).

The data never becomes part of the generated program: it is written to a scratch file whose path is passed
through ``inputs`` and read by a fixed harness, so neither the static policy scan nor argument-length limits
depend on the data.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from mrf.config import get_settings

_HARNESS = """
import json as _json
import pathlib as _pathlib
_result = score(_pathlib.Path(_INPUTS["input_csv"]).read_text(encoding="utf-8"))
print(_json.dumps(_result))
"""


class ScoringError(Exception):
    """The candidate code did not produce scores (crash, timeout, wrong output shape)."""

    def __init__(self, message: str, sandbox: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.sandbox = sandbox or {}


def _scratch_dir() -> Path:
    path = Path(get_settings().data_dir).resolve() / "sandbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def score_csv(code: str, csv_text: str, *, timeout_s: int = 120) -> list[float]:
    """Scores of ``score(csv_text)`` from ``code`` (one float per record). Raises MRF-3003 on a policy violation
    (from ``run_sandbox``) and :class:`ScoringError` when the code runs but does not return usable scores."""
    from mrf.mcp_server.tools.sandbox import run_sandbox

    scratch = _scratch_dir() / f"{uuid.uuid4().hex}.csv"
    scratch.write_text(csv_text, encoding="utf-8")
    try:
        result = await run_sandbox(code + "\n" + _HARNESS, inputs={"input_csv": str(scratch)}, timeout_s=timeout_s)
    finally:
        scratch.unlink(missing_ok=True)
    if result["exit_code"] != 0:
        tail = (result.get("stderr") or "").strip().splitlines()[-3:]
        raise ScoringError("candidate code failed: " + " | ".join(tail)[:500], result)
    outputs = result.get("outputs")
    scores = outputs
    if isinstance(outputs, dict):
        scores = outputs.get("scores") or outputs.get("predictions") or outputs.get("values")
    if not isinstance(scores, list):
        raise ScoringError('candidate did not return {"scores": [...]}', result)
    try:
        return [float(v) for v in scores]
    except (TypeError, ValueError) as exc:
        raise ScoringError("candidate returned non-numeric scores", result) from exc
