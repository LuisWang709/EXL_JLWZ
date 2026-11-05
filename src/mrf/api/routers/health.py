"""Liveness / readiness (used by CD smoke tests). Owner: A4 (wiring by A1)."""

from fastapi import APIRouter, Request

from mrf import __version__
from mrf.core import success

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz(request: Request) -> dict[str, object]:
    return success(request.state.request_id, {"alive": True, "version": __version__}).model_dump(mode="json")


@router.get("/readyz")
async def readyz(request: Request) -> dict[str, object]:
    # TODO(A1/A4): check storage, LLM config and MCP server; return 503 when not ready.
    return success(request.state.request_id, {"ready": True, "checks": {}}).model_dump(mode="json")
