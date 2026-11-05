"""Model documentation agent. Owner: A3.

RAG (search_kb) + MCP tools (parse_code, profile_data, get_inventory); every claim carries
Evidence (file:line or kb chunk). Uses rating feedback on retries. Implements DocWriter.
Template: templates/model_doc.md.j2.
"""
