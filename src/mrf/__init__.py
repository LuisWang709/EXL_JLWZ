"""Model Risk Factory (MRF) - EXL Hackathon Challenge 04, Team A.

Package map (owner in brackets) - see docs/team/README.md:

    mrf.core          shared envelope, return codes, pipeline states       [A1]
    mrf.contracts     shared domain models + agent interfaces (frozen)     [A1, all review]
    mrf.api           FastAPI app, /api/v1 routers, job executor           [A1]
    mrf.orchestrator  LangGraph state machine, retries, human gates        [A1]
    mrf.llm           LLM wrapper (backoff, token/cost, mock)              [A1]
    mrf.storage       repositories (SQLite local / Cosmos cloud), blobs    [A1]
    mrf.mcp_server    MCP tool server framework (/mcp)                     [A1]
    mrf.agents.classify  model identification agent                       [A1]
    mrf.data          data loading/cleaning + pandera schemas              [A2]
    mrf.agents.rebuild   SAS/R -> Python rebuild + parity                 [A2]
    mrf.rag           knowledge base (SS1/23, templates, mapping table)    [A3]
    mrf.agents.doc    model documentation agent                           [A3]
    mrf.rating        rule checks + LLM reviewer                           [A3]
    mrf.validation    performance / stability / fairness metrics           [A3]
    mrf.reporting     analysis & validation report generator               [A3]
    mrf.monitoring    data quality, drift, alerts, scheduled reports       [A4]
    mrf.ui            Streamlit UI                                         [A4]
"""

__version__ = "0.1.0"
