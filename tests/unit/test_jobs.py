from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mrf.contracts.models import Job
from mrf.core import MRFCode, MRFError
from mrf.jobs import JobExecutor, register_handler
from mrf.storage import Collections, get_repo


@register_handler("test_echo")
async def _echo(job: Job) -> dict[str, Any]:
    await asyncio.sleep(0)
    if job.payload.get("fail"):
        raise MRFError(MRFCode.PARITY_FAILED, "nope")
    return {"echo": job.payload.get("x")}


async def test_submit_run_and_wait() -> None:
    async with JobExecutor() as ex:
        job, created = await ex.submit("test_echo", {"model_id": "m"}, payload={"x": 1})
        done = await ex.wait(job.job_id, timeout=5)
    assert created and done.status == "succeeded" and done.result == {"echo": 1} and done.finished_at


async def test_failure_is_recorded_as_envelope_fragment() -> None:
    async with JobExecutor() as ex:
        job, _ = await ex.submit("test_echo", payload={"fail": True})
        done = await ex.wait(job.job_id, timeout=5)
    assert done.status == "failed" and done.error and done.error["code"] == "MRF-3001"


async def test_idempotency() -> None:
    ex = JobExecutor()
    a, c1 = await ex.submit("test_echo", payload={"x": 1}, idempotency_key="k")
    b, c2 = await ex.submit("test_echo", payload={"x": 1}, idempotency_key="k")
    assert a.job_id == b.job_id and c1 and not c2
    with pytest.raises(MRFError) as e:
        await ex.submit("test_echo", payload={"x": 2}, idempotency_key="k")
    assert e.value.code is MRFCode.INPUT_BODY


async def test_recovers_queued_jobs_on_start() -> None:
    await get_repo().put(Collections.JOBS, "job_old", Job(job_id="job_old", kind="test_echo", payload={"x": 7}))
    async with JobExecutor() as ex:
        done = await ex.wait("job_old", timeout=5)
    assert done.result == {"echo": 7}


async def test_unknown_kind_fails_cleanly() -> None:
    ex = JobExecutor()
    job, _ = await ex.submit("nope")
    done = await ex.run_now(job.job_id)
    assert done.status == "failed" and done.error and "no handler" in done.error["message"]


async def test_run_now_without_start_runs_pipeline() -> None:
    from mrf.contracts.models import ArtifactRef
    from mrf.orchestrator.service import create_pipeline

    p, _ = await create_pipeline(model_name="m", source_refs=[ArtifactRef(uri="file:///x.sas", filename="x.sas")])
    ex = JobExecutor()
    job, _ = await ex.submit("pipeline", {"pipeline_id": p.pipeline_id}, payload={"auto_approve": True})
    done = await ex.run_now(job.job_id)
    assert done.status == "succeeded" and done.result and done.result["state"] == "monitoring"
