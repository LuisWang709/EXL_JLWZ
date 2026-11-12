"""Liveness / readiness (used by CD smoke tests and Container Apps probes). Owner: A4 (wiring by A1).

- ``/healthz``: the process is up. Never touches dependencies, so a slow database cannot get the container killed.
- ``/readyz``: the process can serve traffic. Checks storage, the data directory and the LLM configuration;
  any failure -> HTTP 503 with the failing checks listed. It never calls the LLM itself (probes run every few
  seconds and would cost money).
"""

from __future__ import annotations

import os
import tempfile

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from mrf import __version__
from mrf.config import get_settings
from mrf.contracts.models import ModelRecord
from mrf.core import MRFCode, error, success
from mrf.storage import Collections, get_repo

router = APIRouter(tags=["health"])

# provider -> environment variables that must be non-empty (mirrors mrf.llm.openai_client)
_LLM_REQUIRED_ENV: dict[str, tuple[tuple[str, ...], ...]] = {
    "mock": (),
    "azure_openai": (("AZURE_OPENAI_ENDPOINT",),),
    "openai": (("OPENAI_API_KEY",),),
    "github_models": (("GITHUB_TOKEN", "OPENAI_API_KEY"),),  # either one
}


@router.get("/healthz")
async def healthz(request: Request) -> dict[str, object]:
    return success(request.state.request_id, {"alive": True, "version": __version__}).model_dump(mode="json")


async def _check_storage() -> str:
    try:
        await get_repo().find(Collections.MODELS, ModelRecord, page_size=1)
    except Exception as exc:  # any backend error means "not ready"
        return f"error: {type(exc).__name__}"
    return "ok"


def _check_data_dir() -> str:
    data_dir = get_settings().data_dir
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=data_dir, prefix=".readyz-"):
            pass
    except OSError as exc:
        return f"error: {type(exc).__name__}"
    return "ok"


def _check_llm_config() -> str:
    provider = get_settings().llm_provider
    missing = [
        " or ".join(names) for names in _LLM_REQUIRED_ENV.get(provider, ()) if not any(os.environ.get(n) for n in names)
    ]
    return f"missing {', '.join(missing)}" if missing else "ok"


def _check_agents() -> str:
    from mrf.orchestrator.registry import Registry

    try:
        Registry.discover()
    except Exception as exc:
        return f"error: {type(exc).__name__}"
    return "ok"


@router.get("/readyz", response_model=None)
async def readyz(request: Request) -> dict[str, object] | JSONResponse:
    checks = {
        "storage": await _check_storage(),
        "data_dir": _check_data_dir(),
        "llm_config": _check_llm_config(),
        "agents": _check_agents(),
    }
    ready = all(v == "ok" for v in checks.values())
    settings = get_settings()
    # non-secret runtime facts, so a deployment can be verified from outside (which backend / model is live)
    runtime = {
        "env": settings.env,
        "storage_backend": settings.storage_backend,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "guards_enabled": settings.guards_enabled,
    }
    data = {"ready": ready, "checks": checks, "runtime": runtime}
    if ready:
        return success(request.state.request_id, data).model_dump(mode="json")
    env = error(request.state.request_id, MRFCode.INTERNAL, message="Service not ready", data=data)
    return JSONResponse(status_code=503, content=env.model_dump(mode="json"))
