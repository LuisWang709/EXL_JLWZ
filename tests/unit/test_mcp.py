from __future__ import annotations

from typing import Any

import pytest

from mrf.core import MRFCode, MRFError
from mrf.mcp_server.client import InProcessGateway, McpHttpGateway
from mrf.mcp_server.server import build_server


async def fake_profile(dataset_id: str, columns: list[str] | None = None, max_top_values: int = 5) -> dict[str, Any]:
    """Fake profile."""
    if dataset_id == "missing":
        raise MRFError(MRFCode.NOT_FOUND, "no such dataset")
    return {"dataset_id": dataset_id, "row_count": 10}


async def test_inprocess_override_records_and_evidence() -> None:
    tools = InProcessGateway(overrides={"profile_data": fake_profile})
    assert (await tools.call("profile_data", dataset_id="ds_1"))["row_count"] == 10
    with pytest.raises(MRFError) as e:
        await tools.call("profile_data", dataset_id="missing")
    assert e.value.code is MRFCode.NOT_FOUND
    with pytest.raises(MRFError) as e:
        await tools.call("search_kb", query="x")  # not implemented yet -> MRF-5000
    assert e.value.code is MRFCode.INTERNAL
    assert [r.ok for r in tools.records] == [True, False, False]
    assert tools.records[0].evidence().ref == "tool:profile_data#call_1"


async def test_openai_tool_schemas() -> None:
    schemas = await InProcessGateway().as_openai_tools(["parse_code", "search_kb"])
    names = {s["function"]["name"] for s in schemas}
    assert names == {"parse_code", "search_kb"}
    params = next(s for s in schemas if s["function"]["name"] == "search_kb")["function"]["parameters"]
    assert params["required"] == ["query"] and "top_k" in params["properties"]


async def test_mcp_protocol_roundtrip_preserves_mrf_code() -> None:
    gw = McpHttpGateway(target=build_server([fake_profile]))  # MCPServer instance -> in-memory MCP transport
    assert await gw.list_names() == ["fake_profile"]
    assert (await gw.call("fake_profile", dataset_id="ds_9"))["row_count"] == 10
    with pytest.raises(MRFError) as e:
        await gw.call("fake_profile", dataset_id="missing")
    assert e.value.code is MRFCode.NOT_FOUND


async def test_all_seven_tools_registered() -> None:
    names = {t.name for t in await build_server().list_tools()}
    assert len(names) == 7 and "run_parity" in names
