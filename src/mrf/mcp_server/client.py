"""ToolGateway - how agents call MCP tools.

    from mrf.mcp_server.client import get_tools
    tools = get_tools()                                     # per step / per agent run
    chunks = await tools.call("search_kb", query="SS1/23 principle 3", top_k=5)
    schema = await tools.as_openai_tools(["parse_code", "search_kb"])   # for LLM function calling
    tools.records                                           # call log -> Evidence(source="tool", ref=...)

Transports (MRF_TOOL_TRANSPORT):
  * ``inprocess`` (default) - calls the python functions directly; same process as API/worker.
  * ``http`` - real MCP over Streamable HTTP to MRF_MCP_URL (tool server deployed separately).

Tests can replace a tool without touching the registry:
    tools = InProcessGateway(overrides={"profile_data": fake_profile})
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from mrf.config import get_settings
from mrf.contracts.models import Evidence
from mrf.core import MRFCode, MRFError

ToolFn = Callable[..., Awaitable[Any]]
_CODE = re.compile(r"(MRF-\d{4}):\s*(.*)", re.S)


@dataclass
class ToolCallRecord:
    index: int
    name: str
    arguments: dict[str, Any]
    ok: bool
    duration_ms: int
    error_code: str | None = None

    @property
    def ref(self) -> str:
        return f"tool:{self.name}#call_{self.index}"

    def evidence(self, quote: str | None = None) -> Evidence:
        return Evidence(source="tool", ref=self.ref, quote=quote)


@dataclass
class _Recorder:
    records: list[ToolCallRecord] = field(default_factory=list)

    def add(self, name: str, args: dict[str, Any], ok: bool, started: float, code: str | None) -> ToolCallRecord:
        rec = ToolCallRecord(len(self.records) + 1, name, args, ok, int((time.perf_counter() - started) * 1000), code)
        self.records.append(rec)
        return rec


class ToolGateway(Protocol):
    records: list[ToolCallRecord]

    async def call(self, name: str, **arguments: Any) -> Any: ...

    async def list_names(self) -> list[str]: ...

    async def as_openai_tools(self, names: list[str] | None = None) -> list[dict[str, Any]]: ...


def _openai_tool(name: str, description: str | None, schema: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description or "", "parameters": schema}}


class InProcessGateway:
    def __init__(self, overrides: dict[str, ToolFn] | None = None) -> None:
        from mrf.mcp_server.tools import ALL_TOOLS

        self._tools: dict[str, ToolFn] = {fn.__name__: fn for fn in ALL_TOOLS}
        self._tools.update(overrides or {})
        self._recorder = _Recorder()

    @property
    def records(self) -> list[ToolCallRecord]:
        return self._recorder.records

    async def call(self, name: str, **arguments: Any) -> Any:
        fn = self._tools.get(name)
        if fn is None:
            raise MRFError(MRFCode.NOT_FOUND, f"unknown tool '{name}'")
        started = time.perf_counter()
        try:
            result = await fn(**arguments)
        except MRFError as exc:
            self._recorder.add(name, arguments, False, started, exc.code.value)
            raise
        except NotImplementedError as exc:
            self._recorder.add(name, arguments, False, started, MRFCode.INTERNAL.value)
            raise MRFError(MRFCode.INTERNAL, f"tool '{name}' is not implemented yet") from exc
        self._recorder.add(name, arguments, True, started, None)
        return result

    async def list_names(self) -> list[str]:
        return sorted(self._tools)

    async def as_openai_tools(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        from mrf.mcp_server.server import build_server

        server = build_server(list(self._tools.values()))
        tools = await server.list_tools()
        return [_openai_tool(t.name, t.description, t.input_schema) for t in tools if names is None or t.name in names]


class McpHttpGateway:
    """Real MCP client. ``target`` is a URL (Streamable HTTP) or an MCPServer instance (tests)."""

    def __init__(self, target: Any | None = None, timeout_s: float = 120) -> None:
        self.target = target if target is not None else get_settings().mcp_url
        self.timeout_s = timeout_s
        self._recorder = _Recorder()

    @property
    def records(self) -> list[ToolCallRecord]:
        return self._recorder.records

    async def call(self, name: str, **arguments: Any) -> Any:
        from mcp import Client

        started = time.perf_counter()
        async with Client(self.target, read_timeout_seconds=self.timeout_s) as client:
            result = await client.call_tool(name, arguments)
        text = "".join(getattr(c, "text", "") for c in result.content)
        if result.is_error:
            m = _CODE.search(text)
            code = MRFCode(m.group(1)) if m and m.group(1) in {c.value for c in MRFCode} else MRFCode.INTERNAL
            self._recorder.add(name, arguments, False, started, code.value)
            raise MRFError(code, m.group(2) if m else text)
        self._recorder.add(name, arguments, True, started, None)
        if result.structured_content is not None:
            sc = result.structured_content
            return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    async def list_names(self) -> list[str]:
        from mcp import Client

        async with Client(self.target) as client:
            return sorted(t.name for t in (await client.list_tools()).tools)

    async def as_openai_tools(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        from mcp import Client

        async with Client(self.target) as client:
            tools = (await client.list_tools()).tools
        return [_openai_tool(t.name, t.description, t.input_schema) for t in tools if names is None or t.name in names]


def get_tools(overrides: dict[str, ToolFn] | None = None) -> InProcessGateway | McpHttpGateway:
    """New gateway (fresh call log) using the configured transport."""
    if get_settings().tool_transport == "http" and not overrides:
        return McpHttpGateway()
    return InProcessGateway(overrides)
