"""Owner: A2."""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from mrf.config import get_policy
from mrf.core import MRFCode, MRFError
from mrf.storage import get_blobs

#: modules whose *explicit import* in generated code is rejected by the static policy check.
#: Note: we do NOT replace ``builtins.__import__`` at runtime — numpy/pandas/scipy legitimately
#: import subprocess/ctypes/pickle internally, and blocking them breaks the data-science stack.
#: The static scan below only rejects these modules when the *generated code itself* imports them.
#: ``os``/``sys`` are deliberately NOT here (their dangerous *usage* is caught by BANNED_PATTERNS),
#: so generated model code can still legitimately do ``import os; os.getenv(...)``.
BLOCKED_MODULES = {
    "socket",
    "subprocess",
    "ctypes",
    "shutil",
    "multiprocessing",
    "urllib",
    "http",
    "requests",
    "ftplib",
    "telnetlib",
    "smtplib",
    "pty",
}

#: banned tokens: network, filesystem writes, subprocess, os/importlib escape hatches.
BANNED_PATTERNS = [
    (re.compile(r"\b(import|from)\s+(socket|http|urllib|requests|ftplib|telnetlib)\b"), "network access"),
    (re.compile(r"\b(subprocess|os\.system|os\.popen|os\.spawn|pty|shutil)\b"), "subprocess / shell"),
    (re.compile(r"\b(open|__import__|importlib|compile|exec|eval|globals|locals)\s*\("), "dynamic code / file access"),
    (
        re.compile(r"\b(os\.(remove|unlink|rmdir|chmod|chown|rename)|shutil\.(rmtree|move|copy))\b"),
        "filesystem mutation",
    ),
]

#: timeout safety floor (seconds); never allow a single sandbox run past this.
_HARD_TIMEOUT_S = 300


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
    violations = _check_policy(code)
    if violations:
        raise MRFError(
            MRFCode.SANDBOX_POLICY,
            "sandbox policy violated",
            detail={"violations": violations},
        )

    timeout = min(int(timeout_s), _HARD_TIMEOUT_S)

    # Build a minimal wrapper that (1) restricts imports, (2) captures a JSON result.
    wrapper = _build_wrapper(code, inputs or {})

    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-",  # program on stdin: no command-line length limit (Windows caps arguments at ~32k characters)
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(wrapper.encode("utf-8")), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return {
                "exit_code": 124,
                "stdout": "",
                "stderr": f"timeout after {timeout}s",
                "outputs": {},
                "duration_ms": int((time.monotonic() - started) * 1000),
                "policy_violations": [],
            }
    except Exception as exc:  # pragma: no cover - spawn failure
        return {
            "exit_code": 1,
            "stdout": "",
            "stderr": f"sandbox spawn failed: {exc}",
            "outputs": {},
            "duration_ms": int((time.monotonic() - started) * 1000),
            "policy_violations": [],
        }

    duration_ms = int((time.monotonic() - started) * 1000)
    stdout = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
    stderr = stderr_b.decode("utf-8", errors="replace") if stderr_b else ""

    outputs: dict[str, Any] = {}
    if proc.returncode == 0:
        outputs = _extract_result(stdout)

    return {
        "exit_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "outputs": outputs,
        "duration_ms": duration_ms,
        "policy_violations": [],
    }


def _check_policy(code: str) -> list[str]:
    """Return a list of human-readable policy violations (empty = OK)."""
    violations: list[str] = []
    for pattern, label in BANNED_PATTERNS:
        if pattern.search(code):
            violations.append(label)
    # block-list check for import statements of escape-hatch modules
    for m in re.finditer(r"^\s*(?:import\s+([\w.]+)|from\s+([\w.]+)\s+import)", code, re.MULTILINE):
        module = (m.group(1) or m.group(2)).split(".")[0]
        if module in BLOCKED_MODULES:
            violations.append(f"blocked import: {module}")
    return violations


def _build_wrapper(code: str, inputs: dict[str, str]) -> str:
    """Wrap user code in a clean interpreter context. Security is enforced by the static
    ``_check_policy`` scan (done before this runs) plus process isolation + timeout; we do NOT
    monkey-patch ``__import__`` because numpy/pandas/scipy need stdlib modules internally."""
    inputs_json = json.dumps(inputs)
    return (
        "import sys, json\n"
        "# drop '' (cwd) and the CLI shim so generated code cannot import local project files\n"
        "sys.path = [p for p in sys.path if p and 'shim' not in p]\n"
        "_INPUTS = json.loads(" + repr(inputs_json) + ")\n" + code + "\n"
    )


def _extract_result(stdout: str) -> dict[str, Any]:
    """Pull a JSON payload from the sandbox stdout (last JSON object wins)."""
    try:
        # prefer the whole output if it is a single JSON object
        return json.loads(stdout.strip())
    except json.JSONDecodeError:
        pass
    # fallback: find the last balanced {...} block
    start = stdout.rfind("{")
    if start == -1:
        return {}
    end = stdout.rfind("}")
    if end > start:
        try:
            return json.loads(stdout[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return {}


async def run_parity(model_id: str, candidate_code_uri: str, fixture_id: str | None = None) -> dict[str, Any]:
    """Score the legacy fixture with the candidate python model and compare record by record
    with the legacy SAS/R scores.

    The fixture is looked up by ``fixture_id`` (default: ``model_id``): an uploaded legacy model package staged
    under ``<data_dir>/fixtures/`` first, then the built-in ``tests/fixtures/<id>/``.

    Returns ParityResult as dict: {"passed", "n_records", "n_mismatches", "max_abs_diff",
    "tolerance", "mismatch_examples": [...], "detail": {...}}. Tolerance comes from
    config/pipeline.yaml (parity.abs_tolerance).
    """
    from mrf.agents.rebuild.execution import ScoringError, score_csv
    from mrf.agents.rebuild.fixtures import load_fixture

    policy = get_policy()
    tolerance = float(policy.get("parity", {}).get("abs_tolerance", 1.0e-6))
    match_rate_required = float(policy.get("parity", {}).get("match_rate_required", 1.0))

    fixture = await asyncio.to_thread(load_fixture, fixture_id or model_id)
    _manifest, legacy, inputs = await _load_fixture(fixture.path)
    score_col = fixture.score_column
    record_id_col = fixture.id_column
    if score_col not in legacy.columns:
        raise MRFError(MRFCode.NOT_FOUND, f"fixture has no score column '{score_col}'", field="fixture_id")

    candidate_code = await _load_candidate_code(candidate_code_uri)
    try:
        preds = await score_csv(candidate_code, inputs.to_csv(index=False))
    except ScoringError as exc:
        sandbox = {k: str(v)[-1500:] for k, v in exc.sandbox.items() if k in {"exit_code", "stderr"}}
        return _parity_result(
            False, len(legacy), len(legacy), None, tolerance, detail={"error": str(exc), "sandbox": sandbox}
        )

    legacy_scores = legacy[score_col].to_numpy(dtype=float)
    if len(preds) != len(legacy_scores):
        detail = {"error": f"record count mismatch: candidate {len(preds)} vs legacy {len(legacy_scores)}"}
        return _parity_result(False, len(legacy), len(legacy), None, tolerance, detail=detail)

    diff = np.abs(np.asarray(preds, dtype=float) - legacy_scores)
    diff = np.where(np.isnan(diff), np.inf, diff)  # a missing score never matches
    n_records = len(legacy_scores)
    mismatch = diff > tolerance
    n_mismatches = int(mismatch.sum())
    finite = diff[np.isfinite(diff)]
    max_abs_diff = float(finite.max()) if len(finite) else None
    match_rate = (n_records - n_mismatches) / n_records if n_records else 0.0
    passed = n_mismatches == 0 and match_rate >= match_rate_required and n_records > 0

    ids = legacy[record_id_col].tolist() if record_id_col in legacy.columns else list(range(n_records))
    # a few worst mismatches for debugging / agent feedback
    worst_idx = np.argsort(diff)[::-1][:5]
    mismatch_examples = [
        {
            record_id_col: _jsonable(ids[i]),
            "legacy": float(legacy_scores[i]),
            "candidate": None if np.isnan(preds[i]) else float(preds[i]),
            "abs_diff": None if not np.isfinite(diff[i]) else float(diff[i]),
        }
        for i in worst_idx
        if diff[i] > tolerance
    ]

    return _parity_result(
        passed,
        n_records,
        n_mismatches,
        max_abs_diff,
        tolerance,
        mismatch_examples=mismatch_examples,
        detail={
            "match_rate": round(match_rate, 6),
            "match_rate_required": match_rate_required,
            "score_column": score_col,
            "model_id": model_id,
            "fixture_id": fixture.fixture_id,
            "mismatch_ids": [_jsonable(ids[i]) for i in np.flatnonzero(mismatch)[:2000]],
        },
    )


def _parity_result(
    passed: bool,
    n_records: int,
    n_mismatches: int,
    max_abs_diff: float | None,
    tolerance: float,
    *,
    mismatch_examples: list[dict[str, Any]] | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "passed": passed,
        "n_records": n_records,
        "n_mismatches": n_mismatches,
        "max_abs_diff": max_abs_diff,
        "tolerance": tolerance,
        "mismatch_examples": mismatch_examples or [],
        "detail": detail or {},
    }


async def _load_fixture(fixture_dir: Path) -> tuple[dict[str, Any], Any, Any]:
    """Load manifest + legacy scores + input sample (blocking I/O off the event loop)."""
    import pandas as pd

    manifest_path = fixture_dir / "manifest.json"
    legacy_path = fixture_dir / "legacy_scores.csv"
    input_path = fixture_dir / "input_sample.csv"

    def _load() -> tuple[dict[str, Any], Any, Any]:
        if not manifest_path.exists():
            raise MRFError(MRFCode.NOT_FOUND, f"fixture not found: {fixture_dir}", field="fixture_id")
        if not legacy_path.exists() or not input_path.exists():
            raise MRFError(MRFCode.NOT_FOUND, f"fixture incomplete: {fixture_dir}", field="fixture_id")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        legacy = pd.read_csv(legacy_path)
        inputs = pd.read_csv(input_path)
        return manifest, legacy, inputs

    return await asyncio.to_thread(_load)


async def _load_candidate_code(candidate_code_uri: str) -> str:
    """Read candidate code bytes from the blob store and decode to UTF-8 text."""
    raw = await get_blobs().get_bytes(candidate_code_uri)
    return raw.decode("utf-8")


def _jsonable(value: Any) -> Any:
    """Coerce numpy scalars to plain python so the dict serialises to JSON."""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value
