"""CLI: run one pipeline locally, end to end, without the HTTP server.

    uv run python -m mrf.run --model M001                 # stops at H1 (prints the review id)
    uv run python -m mrf.run --model M001 --auto-approve  # H1/H2 auto-approved -> monitoring
    MRF_STUBS=all uv run python -m mrf.run --model M001 --auto-approve   # force stubs for every agent

``--model`` is a folder prefix under models/legacy/ (e.g. M001 -> models/legacy/M001_*) or a path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from mrf.config import REPO_ROOT


def _source_files(model: str) -> tuple[str, list[Path]]:
    path = Path(model)
    if not path.exists():
        matches = sorted((REPO_ROOT / "models" / "legacy").glob(f"{model}*"))
        if not matches:
            raise SystemExit(f"[mrf] no folder models/legacy/{model}* and no path {model}")
        path = matches[0]
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
    code = [f for f in files if f.name.lower() != "readme.md"] or files
    return path.stem if path.is_file() else path.name, code


async def _main(args: argparse.Namespace) -> int:
    from mrf.jobs import JobExecutor, set_executor
    from mrf.orchestrator.registry import Registry
    from mrf.orchestrator.service import UploadedFile, close_orchestrator, create_pipeline, get_orchestrator
    from mrf.storage import get_repo

    name, paths = _source_files(args.model)
    files = [UploadedFile(p.name, p.read_bytes()) for p in paths]
    orch = await get_orchestrator()
    print(f"[mrf] model={name} files={[p.name for p in paths]}")
    print(f"[mrf] agents={json.dumps(Registry.describe(orch.registry))}")

    executor = JobExecutor()
    set_executor(executor)
    pipeline, model = await create_pipeline(model_name=name, files=files, dataset_ids=args.dataset)
    job, _ = await executor.submit(
        "pipeline", {"pipeline_id": pipeline.pipeline_id}, payload={"auto_approve": args.auto_approve}
    )
    job = await executor.run_now(job.job_id)

    from mrf.contracts.models import Pipeline

    p = await get_repo().get("pipelines", pipeline.pipeline_id, Pipeline)
    print(f"[mrf] pipeline={p.pipeline_id} model={model.model_id} job={job.job_id} status={job.status}")
    for t in p.history:
        extra = f"  ({t.note})" if t.note else ""
        print(f"    {t.at:%H:%M:%S}  {t.from_state.value if t.from_state else '-':>22} -> {t.to_state.value}{extra}")
    print(f"[mrf] state={p.state.value} attempts={p.attempts} usage={p.usage.model_dump()}")
    if job.result and job.result.get("waiting_for_review"):
        print(
            f"[mrf] waiting for {job.result['gate']} review {job.result['review_id']} "
            "(POST /api/v1/reviews/{id}/decision, or rerun with --auto-approve)"
        )
    if job.error:
        print(f"[mrf] error {json.dumps(job.error)}", file=sys.stderr)
    await close_orchestrator()
    await get_repo().close()
    return 0 if job.status == "succeeded" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mrf.run", description="Run one MRF pipeline locally")
    parser.add_argument("--model", required=True, help="legacy model id prefix (M001) or a path")
    parser.add_argument("--dataset", action="append", default=[], help="registered dataset id (repeatable)")
    parser.add_argument("--auto-approve", action="store_true", help="auto-approve H1/H2 (MRF_ENV=local only)")
    return asyncio.run(_main(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
