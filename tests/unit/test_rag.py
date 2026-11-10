"""Knowledge base chunking / retrieval and the search_kb MCP tool."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mrf.core import MRFCode, MRFError
from mrf.mcp_server.tools.kb import search_kb
from mrf.rag import COLLECTIONS, KnowledgeBase, get_kb, load_chunks
from mrf.rag.store import parse_front_matter, split_sections


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def kb_root(tmp_path: Path) -> Path:
    root = tmp_path / "kb"
    _write(
        root,
        "ss1_23/principles.md",
        "---\nsource: Test SS1/23\nurl: https://example.org/ss123\nlicence: test\n---\n"
        "# Principle 3\n\n## Documentation\n\nDocumentation must let an independent third party understand "
        "the model.\n\n## Implementation\n\nProduction code is reconciled with the approved design.\n",
    )
    _write(root, "mapping/sas.md", "# Missing values\n\nSAS treats a missing numeric as smaller than any number.\n")
    _write(root, "templates/README.txt", "Template guidance without front matter.\n")
    _write(root, "other/ignored.md", "# Not a collection\n\nignored\n")
    return root


def test_front_matter_and_line_numbers() -> None:
    meta, body, consumed = parse_front_matter("---\nsource: S\nurl: U\n---\nline 5\n")
    assert meta == {"source": "S", "url": "U"} and body == "line 5\n" and consumed == 4
    sections = split_sections("# A\n\ntext a\n## B\ntext b\n", first_line=10)
    assert [(p, t, a, b) for p, t, a, b in sections] == [
        (["A"], "text a", 12, 12),
        (["A", "B"], "text b", 14, 14),
    ]


def test_long_sections_are_split_on_paragraphs() -> None:
    body = "# Big\n\n" + "\n\n".join("word " * 120 for _ in range(4))
    parts = split_sections(body)
    assert len(parts) >= 2 and all(len(t) < 2000 for _, t, _, _ in parts)


def test_load_chunks_reads_collections_only(kb_root: Path) -> None:
    chunks = load_chunks(kb_root)
    assert {c.collection for c in chunks} == {"ss1_23", "mapping", "templates"}
    doc = next(c for c in chunks if "third party" in c.text)
    assert doc.chunk_id == "principles#1" and doc.source == "Test SS1/23" and doc.url == "https://example.org/ss123"
    assert doc.locator.startswith("kb/ss1_23/principles.md > Principle 3 > Documentation (lines ")
    assert next(c for c in chunks if c.collection == "templates").source == "templates/README.txt"


def test_search_ranks_and_filters(kb_root: Path) -> None:
    kb = KnowledgeBase(load_chunks(kb_root))
    hits = kb.search("independent third party documentation", top_k=2)
    assert hits[0]["chunk_id"] == "principles#1" and hits[0]["score"] > 0
    assert set(hits[0]) >= {"chunk_id", "text", "source", "locator", "score"}
    assert [h["collection"] for h in kb.search("missing numeric", collection="mapping")] == ["mapping"]
    assert kb.search("missing numeric", collection="templates") == []
    assert kb.search("zzzz qqqq") == []
    assert kb.get("kb:principles#1") is not None


def test_numpy_and_faiss_backends_agree(kb_root: Path) -> None:
    kb = KnowledgeBase(load_chunks(kb_root))
    plain = KnowledgeBase(load_chunks(kb_root))
    plain._faiss = None
    query = "reconciled production code"
    assert [h["chunk_id"] for h in kb.search(query)] == [h["chunk_id"] for h in plain.search(query)]


def test_index_rebuilds_when_a_file_changes(kb_root: Path) -> None:
    first = get_kb(kb_root)
    assert get_kb(kb_root) is first
    _write(kb_root, "mapping/rounding.md", "# Rounding\n\nSAS ROUND rounds halves away from zero.\n")
    assert get_kb(kb_root) is not first and get_kb(kb_root).search("halves away from zero")


def test_search_kb_tool(kb_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MRF_KB_DIR", str(kb_root))
    hits = asyncio.run(search_kb("third party documentation", top_k=1, collection="ss1_23"))
    assert len(hits) == 1 and hits[0]["chunk_id"] == "principles#1"
    for bad in ({"query": "  "}, {"query": "x", "collection": "nope"}):
        with pytest.raises(MRFError) as err:
            asyncio.run(search_kb(**bad))  # type: ignore[arg-type]
        assert err.value.code == MRFCode.INPUT_BODY


def test_repository_kb_covers_every_collection_and_section_query() -> None:
    kb = get_kb()
    assert {c.collection for c in kb.chunks} == set(COLLECTIONS)
    top = kb.search("model documentation independent third party replicate", top_k=1, collection="ss1_23")
    assert top and "Documentation" in top[0]["text"]
    top = kb.search("PROC LOGISTIC reference level effect coding", top_k=1, collection="mapping")
    assert top and "CLASS" in top[0]["text"]


def test_backend_switch(kb_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MRF_KB_BACKEND", "numpy")
    assert KnowledgeBase(load_chunks(kb_root)).backend == "numpy"
