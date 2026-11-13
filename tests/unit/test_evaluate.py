"""The evaluation harness must fail automation when a run does not meet its checks."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from scripts import evaluate


@pytest.mark.parametrize("state,correct,expected", [
    ("monitoring", True, 0), ("failed", True, 1), ("manual_review", True, 1), ("monitoring", False, 1),
])
async def test_strict_exit_and_raw_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str, correct: bool, expected: int
) -> None:
    monkeypatch.setattr(evaluate, "discover_models", lambda selected: [("M001", [], None)])

    async def run(*args: Any) -> dict[str, Any]:
        return {
            "model": "M001", "pipeline_id": "pl", "final_state": state, "manual_review": state == "manual_review",
            "classification_ok": correct, "agent_s": 1.0, "wall_s": 1.1, "attempts": {"doc": 1, "parity": 1},
            "usage": {"llm_calls": 1, "prompt_tokens": 10, "completion_tokens": 5,
                      "cost_eur": 0.0, "backoff_retries": 0},
            "stubs_seen": [], "validation_complete": False,
        }

    monkeypatch.setattr(evaluate, "run_once", run)
    assert await evaluate.main(["--runs", "1", "--strict", "--out-dir", str(tmp_path)]) == expected
    evidence = await asyncio.to_thread(lambda: json.loads(next(tmp_path.glob("*.json")).read_text("utf-8")))
    assert evidence["meta"]["validation_complete"] is False
    assert "NOT REPORTABLE" in evaluate.to_markdown(evidence["meta"], evidence["summary"])


async def test_require_real_llm_refuses_mock_before_running(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected(*args: Any) -> Any:
        raise AssertionError("should not start evaluation")

    monkeypatch.setattr(evaluate, "discover_models", unexpected)
    assert await evaluate.main(["--require-real-llm"]) == 2


async def test_zero_runs_rejected() -> None:
    with pytest.raises(SystemExit) as exc:
        await evaluate.main(["--runs", "0"])
    assert exc.value.code == 2
