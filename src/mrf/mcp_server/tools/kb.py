"""Owner: A3."""

from __future__ import annotations

from typing import Any


async def search_kb(query: str, top_k: int = 5, collection: str | None = None) -> list[dict[str, Any]]:
    """Semantic search over the knowledge base (SS1/23, doc templates & exemplars,
    SAS/R<->Python mapping table).

    Args:
        collection: 'ss1_23' | 'templates' | 'mapping' | None (all).
    Returns:
        [{"chunk_id": str, "text": str, "source": str, "locator": str, "score": float}]
        ``chunk_id`` is what documents cite as Evidence(source='kb', ref='kb:<chunk_id>').
    """
    raise NotImplementedError
