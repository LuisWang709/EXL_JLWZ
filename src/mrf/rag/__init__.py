"""Knowledge base: SS1/23 text, documentation templates & exemplars, SAS/R<->Python mapping. Owner: A3.

Chunk -> TF-IDF vectors -> index (FAISS when installed, numpy otherwise; Azure AI Search can replace the
backend later behind the same API). Exposed via MCP tool search_kb. Sources live in kb/ (see kb/README.md).

    from mrf.rag import get_kb
    hits = get_kb().search("documentation expectations", top_k=3, collection="ss1_23")
"""

from mrf.rag.store import COLLECTIONS, Chunk, KnowledgeBase, get_kb, kb_dir, load_chunks

__all__ = ["COLLECTIONS", "Chunk", "KnowledgeBase", "get_kb", "kb_dir", "load_chunks"]
