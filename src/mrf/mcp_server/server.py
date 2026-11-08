"""MCP server (official ``mcp`` SDK 2.x, ``MCPServer``). Mounted by the API at ``/mcp``.

Tools come from ``mrf.mcp_server.tools.ALL_TOOLS``; each is wrapped so that an
``MRFError`` reaches the client as ``"MRF-xxxx: message"`` (otherwise the SDK hides it).
Inspect locally: ``npx @modelcontextprotocol/inspector`` -> Streamable HTTP -> http://localhost:8000/mcp/
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from mrf import __version__
from mrf.core import MRFError

ToolFn = Callable[..., Awaitable[Any]]


def wrap_tool(fn: ToolFn) -> ToolFn:
    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except MRFError as exc:
            raise ToolError(f"{exc.code.value}: {exc.message}") from exc
        except NotImplementedError as exc:
            raise ToolError(f"MRF-5000: tool '{fn.__name__}' is not implemented yet") from exc

    return wrapper


def build_server(tools: list[ToolFn] | None = None) -> MCPServer:
    if tools is None:
        from mrf.mcp_server.tools import ALL_TOOLS

        tools = list(ALL_TOOLS)
    server = MCPServer(
        "mrf-tools",
        version=__version__,
        instructions="Model Risk Factory tools. Numbers in documents and reports must come from these tools.",
    )
    for fn in tools:
        server.add_tool(wrap_tool(fn), name=fn.__name__)
    return server


_server: MCPServer | None = None


def get_server() -> MCPServer:
    global _server
    if _server is None:
        _server = build_server()
    return _server
