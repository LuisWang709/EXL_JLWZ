"""Owner: A3."""

from __future__ import annotations

import asyncio
from typing import Any

from mrf.core import MRFCode, MRFError


async def search_kb(query: str, top_k: int = 5, collection: str | None = None) -> list[dict[str, Any]]:
    """Semantic search over the knowledge base (SS1/23, doc templates & exemplars,
    SAS/R<->Python mapping table).

    Args:
        collection: 'ss1_23' | 'templates' | 'mapping' | None (all).
    Returns:
        [{"chunk_id": str, "text": str, "source": str, "locator": str, "score": float}]
        ``chunk_id`` is what documents cite as Evidence(source='kb', ref='kb:<chunk_id>').
    """
    from mrf.rag import COLLECTIONS, get_kb

    if not query or not query.strip():
        raise MRFError(MRFCode.INPUT_BODY, "query must not be empty", field="query")
    if collection is not None and collection not in COLLECTIONS:
        raise MRFError(MRFCode.INPUT_BODY, f"collection must be one of {list(COLLECTIONS)}", field="collection")
    kb = await asyncio.to_thread(get_kb)
    return kb.search(query, top_k=max(1, min(int(top_k), 20)), collection=collection)
