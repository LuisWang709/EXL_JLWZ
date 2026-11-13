"""Evaluation harness (A1, plan 11/11): run every model N times end to end and collect process KPIs.

    # dry run (mock LLM, whatever agents are on main) - checks the harness, numbers are NOT reportable
    uv run python scripts/evaluate.py --runs 2

    # against a deployed API (dev / demo) - H1/H2 are approved through POST /reviews/{id}/decision
    MRF_EVAL_API_KEY=<key> uv run python scripts/evaluate.py --api https://<app>.azurecontainerapps.io --runs 5 --write

    # locally with a real LLM (same env vars as the deployment)
    MRF_LLM_PROVIDER=azure_openai MRF_LLM_MODEL=<deployment> AZURE_OPENAI_ENDPOINT=... AZURE_OPENAI_API_KEY=... \
        uv run python scripts/evaluate.py --runs 5 --dataset <dataset_id> --write

Per run it records: wall time, agent processing time (wall time minus waiting at H1 / H2 / manual review), time
per pipeline state (from the transition history), attempts per retry loop, LLM calls / tokens / EUR cost /
backoff retries (Pipeline.usage), final state, whether it ended in manual review, and whether the classifier
matched the gold inventory record.

Outputs: ``var/eval/<timestamp>.json`` (raw) and, with ``--write``, ``docs/evaluation.md``. Each output says
which LLM and which agent implementations (real vs stub) produced it: numbers from a mock / stub run must never
be copied into the deck (A3 signs off numbers; see docs/team/A3_handoff.md). In ``--api`` mode stubs are
detected from the artifacts themselves ("[stub]" documents, rebuilds without code, runs with ``metrics.stub``).
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
GATE_STATES = {"awaiting_doc_approval", "awaiting_signoff", "manual_review"}
TERMINAL_STATES = {"monitoring", "manual_review", "failed"}


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
    """Seconds spent in each state (until the next transition), summed over loops.
    Accepts StateTransition objects (local) or the JSON dicts the API returns."""

    def state(t: Any) -> str:
        return str(t["to_state"] if isinstance(t, dict) else t.to_state.value)

    def at(t: Any) -> datetime:
        return datetime.fromisoformat(t["at"]) if isinstance(t, dict) else t.at

    out: dict[str, float] = {}
    for cur, nxt in itertools.pairwise(history):
        out[state(cur)] = out.get(state(cur), 0.0) + (at(nxt) - at(cur)).total_seconds()
    return out


def _agent_s(state_s: dict[str, float]) -> float:
    """Processing time only: waiting at the human gates is excluded."""
    return round(sum(v for k, v in state_s.items() if k not in GATE_STATES), 3)


def _row(model_id: str, p: dict[str, Any], wall: float, cls: Any, gold: dict[str, Any] | None) -> dict[str, Any]:
    state_s = _state_durations(p["history"])
    return {
        "model": model_id,
        "pipeline_id": p["pipeline_id"],
        "final_state": p["state"],
        "manual_review": p["state"] == "manual_review",
        "last_error": p.get("last_error"),
        "wall_s": round(wall, 3),
        "agent_s": _agent_s(state_s),
        "state_s": {k: round(v, 3) for k, v in state_s.items()},
        "attempts": p.get("attempts") or {},
        "usage": p["usage"],
        "classification_ok": _classification_ok(cls, gold),
        "confidence": cls.confidence if cls else None,
        "validation_complete": False,
    }


# ------------------------------------------------------------------ local (in-process) mode
async def run_once(model_id: str, files: list[Path], gold: dict[str, Any] | None, datasets: list[str]) -> dict:
    from mrf import jobs, storage
    from mrf.contracts.models import ModelRecord, Pipeline, Run
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
    await executor.run_now(job.job_id)
    wall = time.perf_counter() - t0

    repo = get_repo()
    p = await repo.get(Collections.PIPELINES, pipeline.pipeline_id, Pipeline)
    m = await repo.get(Collections.MODELS, model.model_id, ModelRecord)
    validated = await repo.find(Collections.RUNS, Run, where={"model_id": model.model_id}, page_size=100)
    await service.close_orchestrator()
    return _row(model_id, p.model_dump(mode="json"), wall, m.classification, gold) | {
        "stubs_seen": [],
        "validation_complete": any(r.status == "succeeded" and not r.metrics.get("stub") for r in validated.items),
    }


# ------------------------------------------------------------------ deployed API mode
class ApiClient:
    def __init__(self, base: str, key: str) -> None:
        import httpx

        self.http = httpx.Client(
            base_url=base.rstrip("/"),
            headers={"X-API-Key": key, "X-Operator": "evaluation-harness"},
            timeout=120,
        )

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        response = self.http.get(path, params=params or None)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data

    def post(self, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.http.post(path, **kwargs)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data


def _detect_stubs(api: ApiClient, p: dict[str, Any]) -> list[str]:
    mid, arts, stubs = p["model_id"], p.get("artifacts") or {}, []
    if arts.get("doc_id"):
        doc = api.get(f"/api/v1/models/{mid}/documents/{arts['doc_id']}")
        if doc.get("status") != "success" or "[stub]" in str((doc.get("data") or {}).get("content_md", "")):
            stubs.append("doc_writer")
    if arts.get("rebuild_id"):
        rb = api.get(f"/api/v1/models/{mid}/rebuilds/{arts['rebuild_id']}").get("data") or {}
        if not rb.get("code"):
            stubs.append("rebuilder")
    for run_id in arts.get("run_ids") or []:
        run = api.get(f"/api/v1/models/{mid}/runs/{run_id}").get("data") or {}
        if (run.get("metrics") or {}).get("stub"):
            stubs.append("runner")
            break
    return stubs


async def run_once_api(
    api: ApiClient, model_id: str, files: list[Path], gold: dict[str, Any] | None, datasets: list[str]
) -> dict[str, Any]:
    from mrf.contracts.models import ClassificationResult

    t0 = time.perf_counter()
    started = api.post(
        "/api/v1/pipelines",
        data={"model_name": model_id, "dataset_ids": datasets},
        files=[("files", (f.name, f.read_bytes(), "text/plain")) for f in files],
    )
    if started.get("status") != "accepted":
        raise SystemExit(f"[eval] upload rejected: {started.get('code')} {started.get('message')}")
    pid = started["data"]["pipeline_id"]
    approvals, deadline = 0, time.monotonic() + 3600
    while time.monotonic() < deadline:
        p = api.get(f"/api/v1/pipelines/{pid}")["data"]
        if p["state"] in TERMINAL_STATES:
            break
        if p["state"] in {"awaiting_doc_approval", "awaiting_signoff"}:
            pending = api.get("/api/v1/reviews", status="pending", page_size=100)["data"]["items"]
            mine = [r for r in pending if r["pipeline_id"] == pid]
            if mine:
                api.post(
                    f"/api/v1/reviews/{mine[0]['review_id']}/decision",
                    json={"decision": "approve", "comment": "evaluation harness"},
                )
                approvals += 1
        await asyncio.sleep(3)
    wall = time.perf_counter() - t0
    p = api.get(f"/api/v1/pipelines/{pid}")["data"]
    model = api.get(f"/api/v1/models/{p['model_id']}")["data"]
    cls = ClassificationResult.model_validate(model["classification"]) if model.get("classification") else None
    run_ids = (p.get("artifacts") or {}).get("run_ids") or []
    validated = [api.get(f"/api/v1/models/{p['model_id']}/runs/{rid}")["data"] for rid in run_ids]
    return _row(model_id, p, wall, cls, gold) | {
        "stubs_seen": _detect_stubs(api, p),
        "approvals": approvals,
        "validation_complete": any(r.get("status") == "succeeded" and not r.get("metrics", {}).get("stub")
                                   for r in validated),
    }


# ------------------------------------------------------------------ report
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
                "median_agent_s": med([r["agent_s"] for r in rs]),
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
    reportable = (
        meta["llm_provider"] not in {"mock", "unknown"}
        and not meta["stub_agents"]
        and meta.get("validation_complete", False)
    )
    lines = [
        "# Evaluation results",
        "",
        f"Generated {meta['generated_at']} · Target `{meta['target']}` · "
        f"LLM `{meta['llm_provider']}` / `{meta['llm_model']}` · "
        f"{meta['runs_per_model']} runs per model · commit `{meta['commit']}`",
        "",
    ]
    if not reportable:
        lines += [
            "> **NOT REPORTABLE**: this run used a mock/unknown LLM, stub agents, or incomplete dataset scoring "
            f"(stubs: {', '.join(meta['stub_agents']) or 'none'}). "
            "This verifies the evaluation script only; do not use these numbers in presentation results.",
            "",
        ]
    lines += [
        "Generated by `scripts/evaluate.py`; raw evidence: `" + meta["raw_file"] + "`. "
        "H1/H2 are automatically approved for evaluation; agent duration excludes waiting at human gates.",
        "",
        "| Model | Runs | Reached monitoring | Manual review | Identification accuracy | Median agent time (s) "
        "| Document attempts | Parity attempts | LLM calls | Tokens | Cost (EUR) | Backoff retries |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        acc = "—" if r["classification_accuracy"] is None else f"{r['classification_accuracy']:.0%}"
        lines.append(
            f"| {r['model']} | {r['runs']} | {r['reached_monitoring']} | {r['manual_review']} | {acc} "
            f"| {r['median_agent_s']} | {r['median_doc_attempts']} | {r['median_parity_attempts']} "
            f"| {r['median_llm_calls']} | {r['median_tokens']:.0f} | {r['median_cost_eur']} | {r['backoff_retries']} |"
        )
    lines += ["", f"Agent implementations: `{json.dumps(meta['agents'])}`", ""]
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
    ap.add_argument("--api", help="base URL of a deployed API (key from MRF_EVAL_API_KEY)")
    ap.add_argument("--write", action="store_true", help="also write docs/evaluation.md")
    ap.add_argument("--report-out", type=Path, help="write markdown to a separate file (e.g. a CI artifact directory)")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any pipeline fails, escalates or uses stubs")
    ap.add_argument("--require-real-llm", action="store_true", help="refuse mock/unknown providers before running")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "var" / "eval", help="raw results directory")
    args = ap.parse_args(argv)
    if args.runs < 1:
        ap.error("--runs must be at least 1")

    api: ApiClient | None = None
    stubs: set[str] = set()
    if args.api:
        key = os.environ.get("MRF_EVAL_API_KEY")
        if not key:
            print("set MRF_EVAL_API_KEY", file=sys.stderr)
            return 2
        api = ApiClient(args.api, key)
        runtime = (api.get("/readyz").get("data") or {}).get("runtime") or {}
        agents: dict[str, str] = {"remote": "stubs detected from artifacts (stubs_seen per run)"}
        llm_provider = str(runtime.get("llm_provider", "unknown"))
        llm_model = str(runtime.get("llm_model", "unknown"))
    else:
        from mrf.config import get_settings
        from mrf.orchestrator.registry import Registry

        agents = Registry.discover().describe()
        stubs = {k for k, v in agents.items() if v.startswith("Stub")}
        llm_provider, llm_model = get_settings().llm_provider, get_settings().llm_model

    if args.require_real_llm and llm_provider in {"mock", "unknown"}:
        print("real LLM required; configure the provider before evaluation", file=sys.stderr)
        if api is not None:
            api.http.close()
        return 2

    models = discover_models(args.model)
    if not models:
        print("no models found", file=sys.stderr)
        return 1

    runs: list[dict[str, Any]] = []
    for model_id, files, gold in models:
        for i in range(args.runs):
            if api is not None:
                r = await run_once_api(api, model_id, files, gold, args.dataset)
            else:
                r = await run_once(model_id, files, gold, args.dataset)
            stubs |= set(r["stubs_seen"])
            runs.append(r)
            print(
                f"[eval] {model_id} run {i + 1}/{args.runs}: {r['final_state']} agent={r['agent_s']}s "
                f"attempts={r['attempts']} calls={r['usage']['llm_calls']} stubs={r['stubs_seen']}"
            )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / f"{stamp}.json"
    meta = {
        "generated_at": stamp,
        "target": args.api or "local",
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "runs_per_model": args.runs,
        "agents": agents,
        "stub_agents": sorted(stubs),
        "commit": _git_commit(),
        "raw_file": raw.as_posix(),
        "validation_complete": all(r["validation_complete"] for r in runs),
    }
    rows = summarise(runs)
    raw.write_text(json.dumps({"meta": meta, "summary": rows, "runs": runs}, indent=2, default=str), "utf-8")
    md = to_markdown(meta, rows)
    print(md)
    if args.write:
        (ROOT / "docs" / "evaluation.md").write_text(md, encoding="utf-8", newline="\n")
        print("[eval] wrote docs/evaluation.md")
    if args.report_out:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(md, encoding="utf-8", newline="\n")
    if api is not None:
        api.http.close()
    failed = any(r["final_state"] != "monitoring" or r["classification_ok"] is False for r in runs)
    return 1 if args.strict and (failed or stubs) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
