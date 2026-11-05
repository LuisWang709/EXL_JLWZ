"""App factory. Run locally: ``uv run uvicorn mrf.api.app:app --reload``."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from mrf import __version__
from mrf.api.routers import ROUTERS, health
from mrf.core import MRFCode, MRFError, error
from mrf.core.envelope import ErrorItem
from mrf.core.ids import new_request_id


def _request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    return rid or new_request_id()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Model Risk Factory API",
        version=__version__,
        description="EXL Hackathon C04 - Team A. Contract: openapi.yaml (v1).",
    )

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = request.headers.get("X-Request-ID") or new_request_id()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(MRFError)
    async def mrf_error_handler(request: Request, exc: MRFError) -> JSONResponse:
        env = error(
            _request_id(request),
            exc.code,
            message=exc.message,
            errors=[ErrorItem(code=exc.code.value, message=exc.message, field=exc.field, detail=exc.detail)],
        )
        return JSONResponse(status_code=exc.http_status, content=env.model_dump(mode="json"))

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

    app.include_router(health.router)
    for router in ROUTERS:
        app.include_router(router, prefix="/api/v1")
    # TODO(A1, 11/5): mount MCP server at /mcp and start job workers in lifespan.
    return app


app = create_app()
