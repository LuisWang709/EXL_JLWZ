"""In-process async job executor (asyncio queue + ``jobs`` collection). Owner: A1.

Every 202 endpoint does the same thing:

    from mrf.jobs import get_executor, register_handler

    @register_handler("rebuild")                    # once, at import time of your module
    async def run_rebuild(job: Job) -> dict:        # return value -> Job.result
        ...                                         # raise MRFError -> Job.error

    job, created = await get_executor().submit(
        "rebuild", resource={"model_id": model_id}, payload=body, idempotency_key=key)

Recovery: on start, queued/running jobs are re-queued; pipeline jobs continue from the LangGraph
checkpoint. Jobs touching the same resource (``pipeline_id`` or ``model_id``) run one at a time.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

from mrf.config import get_settings
from mrf.contracts.models import Job, utcnow
from mrf.core import MRFCode, MRFError
from mrf.core.ids import new_id
from mrf.storage import Collections, Repository, get_repo

log = logging.getLogger(__name__)

Handler = Callable[[Job], Awaitable[dict[str, Any] | None]]
_HANDLERS: dict[str, Handler] = {}


def register_handler(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        _HANDLERS[kind] = fn
        return fn

    return deco


class _Idem(BaseModel):
    body_sha256: str
    job_id: str


def body_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


class JobExecutor:
    def __init__(self, repo: Repository | None = None, concurrency: int | None = None) -> None:
        self.repo = repo or get_repo()
        self.concurrency = concurrency or get_settings().worker_concurrency
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task[None]] = []
        self._locks: dict[str, asyncio.Lock] = {}
        self._done: dict[str, asyncio.Event] = {}
        self._submit_lock = asyncio.Lock()

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self._workers:
            return
        _import_default_handlers()
        pending = await self.repo.find(
            Collections.JOBS, Job, where={"status": ["queued", "running"]}, page_size=10_000, order_by="created_at"
        )
        for job in pending.items:
            log.info("recovering job %s (%s)", job.job_id, job.status)
            self._queue.put_nowait(job.job_id)
        self._workers = [asyncio.create_task(self._worker(i), name=f"mrf-worker-{i}") for i in range(self.concurrency)]

    async def stop(self, timeout: float = 10) -> None:
        for w in self._workers:
            w.cancel()
        if self._workers:
            await asyncio.wait(self._workers, timeout=timeout)
        self._workers = []

    async def __aenter__(self) -> JobExecutor:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    # ------------------------------------------------------------------ API
    async def submit(
        self,
        kind: str,
        resource: dict[str, str] | None = None,
        *,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[Job, bool]:
        """Returns (job, created). Same key + same body -> the existing job; different body -> MRF-1006."""
        payload = payload or {}
        digest = body_hash({"resource": resource, "payload": payload})
        async with self._submit_lock:
            if idempotency_key:
                scoped = f"{kind}:{idempotency_key}"
                record = await self.repo.get_or_none(Collections.IDEMPOTENCY, scoped, _Idem)
                if record is not None:
                    if record.body_sha256 != digest:
                        raise MRFError(MRFCode.INPUT_BODY, "Idempotency-Key reused with a different request body")
                    return await self.repo.get(Collections.JOBS, record.job_id, Job), False
            job = Job(
                job_id=new_id("job"),
                kind=kind,
                resource=resource or {},
                payload=payload,
                idempotency_key=idempotency_key,
            )
            await self.repo.put(Collections.JOBS, job.job_id, job)
            if idempotency_key:
                await self.repo.put(
                    Collections.IDEMPOTENCY, f"{kind}:{idempotency_key}", _Idem(body_sha256=digest, job_id=job.job_id)
                )
        self._done[job.job_id] = asyncio.Event()
        self._queue.put_nowait(job.job_id)
        return job, True

    async def lookup_idempotent(self, scope: str, key: str, digest: str) -> Job | None:
        """For endpoints that must check the key *before* doing work (e.g. storing uploads)."""
        record = await self.repo.get_or_none(Collections.IDEMPOTENCY, f"{scope}:{key}", _Idem)
        if record is None:
            return None
        if record.body_sha256 != digest:
            raise MRFError(MRFCode.INPUT_BODY, "Idempotency-Key reused with a different request body")
        return await self.repo.get(Collections.JOBS, record.job_id, Job)

    async def remember_idempotent(self, scope: str, key: str, digest: str, job_id: str) -> None:
        await self.repo.put(Collections.IDEMPOTENCY, f"{scope}:{key}", _Idem(body_sha256=digest, job_id=job_id))

    async def wait(self, job_id: str, timeout: float = 60) -> Job:
        """Block until the job finishes (CLI / tests)."""
        event = self._done.setdefault(job_id, asyncio.Event())
        job = await self.repo.get(Collections.JOBS, job_id, Job)
        if job.status not in {"succeeded", "failed", "cancelled"}:
            await asyncio.wait_for(event.wait(), timeout)
        return await self.repo.get(Collections.JOBS, job_id, Job)

    async def run_now(self, job_id: str) -> Job:
        """Execute synchronously in the caller's task (no workers needed)."""
        await self._execute(job_id)
        return await self.repo.get(Collections.JOBS, job_id, Job)

    # ------------------------------------------------------------------ internals
    async def _worker(self, idx: int) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await self._execute(job_id)
            except Exception:  # never let a worker die
                log.exception("worker %d crashed on %s", idx, job_id)
            finally:
                self._queue.task_done()

    async def _execute(self, job_id: str) -> None:
        job = await self.repo.get(Collections.JOBS, job_id, Job)
        if job.status in {"succeeded", "failed", "cancelled"}:
            self._signal(job_id)
            return
        lock_key = job.resource.get("pipeline_id") or job.resource.get("model_id") or job_id
        async with self._locks.setdefault(lock_key, asyncio.Lock()):
            job.status, job.started_at = "running", utcnow()
            await self.repo.put(Collections.JOBS, job_id, job)
            _import_default_handlers()
            handler = _HANDLERS.get(job.kind)
            try:
                if handler is None:
                    raise MRFError(MRFCode.INTERNAL, f"no handler registered for job kind '{job.kind}'")
                job.result = await handler(job) or {}
                job.status, job.progress = "succeeded", 1.0
            except MRFError as exc:
                job.status = "failed"
                job.error = {"code": exc.code.value, "message": exc.message, "detail": exc.detail}
            except Exception as exc:
                log.exception("job %s failed", job_id)
                job.status = "failed"
                job.error = {"code": MRFCode.INTERNAL.value, "message": f"{type(exc).__name__}: {exc}"[:500]}
            job.finished_at = utcnow()
            await self.repo.put(Collections.JOBS, job_id, job)
        self._signal(job_id)

    def _signal(self, job_id: str) -> None:
        event = self._done.get(job_id)
        if event is not None:
            event.set()


def _import_default_handlers() -> None:
    """Modules that register handlers at import time (router modules may define handlers too)."""
    import mrf.api.routers
    import mrf.orchestrator.handlers  # noqa: F401


_executor: JobExecutor | None = None


def get_executor() -> JobExecutor:
    global _executor
    if _executor is None:
        _executor = JobExecutor()
    return _executor


def set_executor(executor: JobExecutor | None) -> None:
    global _executor
    _executor = executor
