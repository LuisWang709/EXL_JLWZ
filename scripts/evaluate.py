"""Evaluation harness (A1, plan 11/11): run every model N times end to end and collect process KPIs.

    # dry run (mock LLM, whatever agents are on main) - checks the harness, numbers are NOT reportable
    uv run python scripts/evaluate.py --runs 2

    # the real evaluation, with the demo LLM configuration (same env vars as the deployment)
    MRF_LLM_PROVIDER=azure_openai MRF_LLM_MODEL=<deployment> AZURE_OPENAI_ENDPOINT=... AZURE_OPENAI_API_KEY=... \
        uv run python scripts/evaluate.py --runs 5 --dataset <dataset_id> --write

Per run it records: wall time, time per pipeline state (from the transition history), attempts per retry loop,
LLM calls / tokens / EUR cost / backoff retries (Pipeline.usage), final state, whether it ended in manual review,
and whether the classifier matched the gold inventory record.

Outputs: ``var/eval/<timestamp>.json`` (raw) and, with ``--write``, ``docs/evaluation.md``. Each output says
which LLM provider and which agent implementations (real vs stub) produced it: numbers from a mock / stub run
must never be copied into the deck (A3 signs off numbers; see docs/team/A3_handoff.md).
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import os
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("MRF_STORAGE_BACKEND", "memory")  # evaluation never touches the local demo database
os.environ.setdefault("MRF_ENV", "local")  # H1/H2 auto-approval is only honoured locally

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CODE_SUFFIXES = (".sas", ".r", ".py", ".ipynb")


def discover_models(selected: list[str]) -> list[tuple[str, list[Path], dict[str, Any] | None]]:
    """Real legacy models (models/legacy/M00x_*/) when they contain code, else the classifier fixtures."""
    out: list[tuple[str, list[Path], dict[str, Any] | None]] = []
    for folder in sorted((ROOT / "models" / "legacy").glob("M0*")):
        code = [p for p in sorted(folder.rglob("*")) if p.is_file() and p.suffix.lower() in CODE_SUFFIXES]
        if code:
            gold_file = ROOT / "tests" / "fixtures" / folder.name[:4].lower() / "inventory_gold.json"
            gold = json.loads(gold_file.read_text(encoding="utf-8")) if gold_file.exists() else None
            out.append((folder.name[:4], code, gold))
    if not out:
        fixtures = ROOT / "tests" / "fixtures" / "classify"
        gold_all = json.loads((fixtures / "gold.json").read_text(encoding="utf-8"))
        for name, gold in gold_all.items():
            if not name.startswith("_"):
                out.append((name.split("_")[0].upper(), [fixtures / name], gold))
    return [m for m in out if not selected or m[0] in selected]


def _classification_ok(cls: Any, gold: dict[str, Any] | None) -> bool | None:
    if gold is None or cls is None:
        return None
    return bool(
        cls.language.value == gold.get("language")
        and cls.algorithm == gold.get("algorithm")
        and cls.purpose == gold.get("purpose")
        and (gold.get("target") is None or cls.target == gold.get("target"))
    )


def _state_durations(history: list[Any]) -> dict[str, float]:
    """Seconds spent in each state (until the next transition), summed over loops."""
    out: dict[str, float] = {}
    for cur, nxt in itertools.pairwise(history):
        out[cur.to_state.value] = out.get(cur.to_state.value, 0.0) + (nxt.at - cur.at).total_seconds()
    return out


async def run_once(model_id: str, files: list[Path], gold: dict[str, Any] | None, datasets: list[str]) -> dict:
    from mrf import jobs, storage
    from mrf.contracts.models import ModelRecord, Pipeline
    from mrf.orchestrator import service
    from mrf.orchestrator.service import UploadedFile, create_pipeline
    from mrf.storage import Collections, get_repo

    storage.set_repo(storage.MemoryRepository())
    jobs.set_executor(None)
    service.set_orchestrator(None)
    executor = jobs.JobExecutor()
    jobs.set_executor(executor)

    t0 = time.perf_counter()
    pipeline, model = await create_pipeline(
        model_name=model_id, files=[UploadedFile(p.name, p.read_bytes()) for p in files], dataset_ids=datasets
    )
    job, _ = await executor.submit("pipeline", {"pipeline_id": pipeline.pipeline_id}, payload={"auto_approve": True})
    job = await executor.run_now(job.job_id)
    wall = time.perf_counter() - t0

    repo = get_repo()
    p = await repo.get(Collections.PIPELINES, pipeline.pipeline_id, Pipeline)
    m = await repo.get(Collections.MODELS, model.model_id, ModelRecord)
    await service.close_orchestrator()
    return {
        "model": model_id,
        "final_state": p.state.value,
        "manual_review": p.state.value == "manual_review",
        "last_error": p.last_error,
        "wall_s": round(wall, 3),
        "state_s": {k: round(v, 3) for k, v in _state_durations(p.history).items()},
        "attempts": p.attempts,
        "usage": p.usage.model_dump(),
        "classification_ok": _classification_ok(m.classification, gold),
        "confidence": m.classification.confidence if m.classification else None,
    }


def summarise(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for model in sorted({r["model"] for r in runs}):
        rs = [r for r in runs if r["model"] == model]
        cls = [r["classification_ok"] for r in rs if r["classification_ok"] is not None]

        def med(values: list[float]) -> float:
            return round(statistics.median(values), 3) if values else 0.0

        rows.append(
            {
                "model": model,
                "runs": len(rs),
                "reached_monitoring": sum(r["final_state"] == "monitoring" for r in rs),
                "manual_review": sum(r["manual_review"] for r in rs),
                "classification_accuracy": round(sum(cls) / len(cls), 3) if cls else None,
                "median_wall_s": med([r["wall_s"] for r in rs]),
                "median_doc_attempts": med([r["attempts"].get("doc", 0) for r in rs]),
                "median_parity_attempts": med([r["attempts"].get("parity", 0) for r in rs]),
                "median_llm_calls": med([r["usage"]["llm_calls"] for r in rs]),
                "median_tokens": med([r["usage"]["prompt_tokens"] + r["usage"]["completion_tokens"] for r in rs]),
                "median_cost_eur": round(statistics.median([r["usage"]["cost_eur"] for r in rs]), 5),
                "backoff_retries": sum(r["usage"]["backoff_retries"] for r in rs),
            }
        )
    return rows


def to_markdown(meta: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    reportable = meta["llm_provider"] != "mock" and not meta["stub_agents"]
    lines = [
        "# 评估结果 / Evaluation",
        "",
        f"生成时间 {meta['generated_at']} · LLM `{meta['llm_provider']}` / `{meta['llm_model']}` · "
        f"每个模型 {meta['runs_per_model']} 次 · commit `{meta['commit']}`",
        "",
    ]
    if not reportable:
        lines += [
            "> **不可用于报告**：本次使用了 mock LLM 或 stub 智能体"
            f"（stub：{', '.join(meta['stub_agents']) or '无'}）。只验证评估脚本本身，数字不得进入 PPT。",
            "",
        ]
    lines += [
        "由 `scripts/evaluate.py` 生成，原始数据见 `" + meta["raw_file"] + "`。H1/H2 在评估中自动批准，"
        "所以耗时只含智能体处理时间，不含人工等待。",
        "",
        "| 模型 | 次数 | 到达监控 | 转人工 | 识别准确率 | 耗时中位数 (s) | 说明书尝试 | 一致性尝试 "
        "| LLM 调用 | tokens | 费用 (EUR) | 退让次数 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        acc = "—" if r["classification_accuracy"] is None else f"{r['classification_accuracy']:.0%}"
        lines.append(
            f"| {r['model']} | {r['runs']} | {r['reached_monitoring']} | {r['manual_review']} | {acc} "
            f"| {r['median_wall_s']} | {r['median_doc_attempts']} | {r['median_parity_attempts']} "
            f"| {r['median_llm_calls']} | {r['median_tokens']:.0f} | {r['median_cost_eur']} | {r['backoff_retries']} |"
        )
    lines += ["", f"智能体实现：`{json.dumps(meta['agents'])}`", ""]
    return "\n".join(lines)


def _git_commit() -> str:
    import subprocess

    out = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    return out.stdout.strip()


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--model", action="append", default=[], help="M001 ... (default: all)")
    ap.add_argument("--dataset", action="append", default=[], help="registered dataset id for the usability run")
    ap.add_argument("--write", action="store_true", help="also write docs/evaluation.md")
    args = ap.parse_args(argv)

    from mrf.config import get_settings
    from mrf.orchestrator.registry import Registry

    registry = Registry.discover()
    agents = registry.describe()
    stubs = sorted(k for k, v in agents.items() if v.startswith("Stub"))
    settings = get_settings()
    models = discover_models(args.model)
    if not models:
        print("no models found", file=sys.stderr)
        return 1

    runs: list[dict[str, Any]] = []
    for model_id, files, gold in models:
        for i in range(args.runs):
            r = await run_once(model_id, files, gold, args.dataset)
            runs.append(r)
            print(
                f"[eval] {model_id} run {i + 1}/{args.runs}: {r['final_state']} "
                f"{r['wall_s']}s attempts={r['attempts']} calls={r['usage']['llm_calls']}"
            )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ROOT / "var" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / f"{stamp}.json"
    commit = _git_commit()
    meta = {
        "generated_at": stamp,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "runs_per_model": args.runs,
        "agents": agents,
        "stub_agents": stubs,
        "commit": commit,
        "raw_file": f"var/eval/{raw.name}",
    }
    rows = summarise(runs)
    raw.write_text(json.dumps({"meta": meta, "summary": rows, "runs": runs}, indent=2, default=str), "utf-8")
    md = to_markdown(meta, rows)
    print(md)
    if args.write:
        (ROOT / "docs" / "evaluation.md").write_text(md, encoding="utf-8", newline="\n")
        print("[eval] wrote docs/evaluation.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
