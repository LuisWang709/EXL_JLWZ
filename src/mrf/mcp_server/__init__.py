"""MCP tool server. Framework owner: A1 (official ``mcp`` SDK / FastMCP, Streamable HTTP at /mcp).

Each tool lives in ``mrf.mcp_server.tools.<area>`` and is owned by the module owner:

    tool             file                 owner   returns
    parse_code       tools/inventory.py   A1      ParsedCode dict
    get_inventory    tools/inventory.py   A1      ModelRecord dict(s)
    profile_data     tools/data.py        A2      DataProfile dict
    run_sandbox      tools/sandbox.py     A2      SandboxResult dict
    run_parity       tools/sandbox.py     A2      ParityResult dict
    search_kb        tools/kb.py          A3      list[KBChunk]
    compute_metrics  tools/metrics.py     A3      dict[metric, value]

Rules: tools are pure functions of their inputs + stored artefacts, return JSON-serialisable
dicts, raise MRFError on failure, and never call an LLM. Agents never compute numbers
themselves - they call these tools (anti-hallucination rule in the plan).
"""
