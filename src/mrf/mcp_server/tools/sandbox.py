"""Owner: A2."""

from __future__ import annotations

from typing import Any


async def run_sandbox(code: str, inputs: dict[str, str] | None = None, timeout_s: int = 120) -> dict[str, Any]:
    """Execute generated Python in an isolated sandbox (no network, allow-listed imports).

    Args:
        code: python source.
        inputs: logical name -> artefact/dataset uri mounted read-only.
    Returns:
        {"exit_code": int, "stdout": str, "stderr": str, "outputs": {name: uri},
         "duration_ms": int, "policy_violations": [str]}
    Raises MRF-3003 if the code violates sandbox policy before running.
    """
    raise NotImplementedError


async def run_parity(model_id: str, candidate_code_uri: str, fixture_id: str | None = None) -> dict[str, Any]:
    """Score the legacy fixture with the candidate python model and compare record by record
    with the legacy SAS/R scores (tests/fixtures/<model>/).

    Returns ParityResult as dict: {"passed", "n_records", "n_mismatches", "max_abs_diff",
    "tolerance", "mismatch_examples": [...], "detail": {...}}. Tolerance comes from
    config/pipeline.yaml (parity.abs_tolerance).
    """
    raise NotImplementedError
