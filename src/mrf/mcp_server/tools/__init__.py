"""Tool contracts. Signatures + docstrings are the contract (the docstring becomes the MCP
tool description the LLM sees, so keep it precise). Owners replace ``NotImplementedError``."""

from mrf.mcp_server.tools import data, inventory, kb, metrics, sandbox

ALL_TOOLS = [
    inventory.parse_code,
    inventory.get_inventory,
    data.profile_data,
    sandbox.run_sandbox,
    sandbox.run_parity,
    kb.search_kb,
    metrics.compute_metrics,
]

__all__ = ["ALL_TOOLS"]
