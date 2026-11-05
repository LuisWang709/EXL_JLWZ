"""LangGraph orchestrator. Owner: A1.

State machine: received -> classified -> doc_drafting <-> doc_rating -> awaiting_doc_approval (H1)
-> rebuilding (self-heal loop) -> parity_passed -> usability_run -> awaiting_signoff (H2)
-> deployed -> monitoring; any step -> manual_review | failed.

Planned modules: state.py (graph state), graph.py (build_graph), nodes.py (one node per step,
calls mrf.contracts.agents implementations), policy.py (retry counting from config/pipeline.yaml),
gates.py (H1/H2 via LangGraph interrupt), audit.py (state transitions -> storage + telemetry),
registry.py (wires concrete agent implementations or stubs).
"""
