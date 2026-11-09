"""App factory. Run locally: ``uv run uvicorn mrf.api.app:app --reload``.

One process hosts: /api/v1 (REST), /mcp (MCP tools, Streamable HTTP), the job workers.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from mrf import __version__
from mrf.api.deps import ApiKey
from mrf.api.routers import ROUTERS, health
from mrf.core import MRFCode, MRFError, error
from mrf.core.envelope import ErrorItem
from mrf.core.ids import new_request_id

log = logging.getLogger(__name__)


def _request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    return rid or new_request_id()


def create_app(*, mount_mcp: bool = True, start_workers: bool = True) -> FastAPI:
    from mrf import telemetry

    telemetry.configure()  # App Insights when APPLICATIONINSIGHTS_CONNECTION_STRING is set
    from mrf.mcp_server.server import build_server

    mcp = build_server() if mount_mcp else None  # fresh per app: a session manager runs only once
    mcp_app = (
        mcp.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True) if mcp else None
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        from mrf.jobs import get_executor
        from mrf.orchestrator.service import close_orchestrator
        from mrf.storage import get_repo

        async with AsyncExitStack() as stack:
            if mcp is not None:
                await stack.enter_async_context(mcp.session_manager.run())
            if start_workers:
                await stack.enter_async_context(get_executor())
            yield
        await close_orchestrator()
        await get_repo().close()

    app = FastAPI(
        title="Model Risk Factory API",
        version=__version__,
        description="EXL Hackathon C04 - Team A. Contract: openapi.yaml (v1).",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = request.headers.get("X-Request-ID") or new_request_id()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(MRFError)
    async def mrf_error_handler(request: Request, exc: MRFError) -> JSONResponse:
        status = 401 if exc.field == "X-API-Key" else exc.http_status
        env = error(
            _request_id(request),
            exc.code,
            message=exc.message,
            errors=[ErrorItem(code=exc.code.value, message=exc.message, field=exc.field, detail=exc.detail)],
        )
        return JSONResponse(status_code=status, content=env.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        items = [
            ErrorItem(
                code=MRFCode.INPUT_BODY.value,
                message=str(e.get("msg")),
                field=".".join(str(p) for p in e.get("loc", [])),
            )
            for e in exc.errors()
        ]
        env = error(_request_id(request), MRFCode.INPUT_BODY, errors=items)
        return JSONResponse(status_code=422, content=env.model_dump(mode="json"))

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = MRFCode.NOT_FOUND if exc.status_code == 404 else MRFCode.INPUT_BODY
        env = error(_request_id(request), code, message=str(exc.detail))
        return JSONResponse(status_code=exc.status_code, content=env.model_dump(mode="json"))

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        env = error(_request_id(request), MRFCode.INTERNAL)
        return JSONResponse(status_code=500, content=env.model_dump(mode="json"))

    app.include_router(health.router)
    for router in ROUTERS:
        app.include_router(router, prefix="/api/v1", dependencies=[ApiKey])
    if mcp_app is not None:
        app.mount("/mcp", mcp_app)
    return app


app = create_app()
