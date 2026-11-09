"""Knowledge-base loading, chunking and retrieval behind the ``search_kb`` MCP tool. Owner: A3.

Sources: ``kb/<collection>/*.md|*.txt`` (collections: ss1_23, templates, mapping). Each file may start with
front-matter that the search results cite::

    ---
    source: PRA SS1/23 - Model risk management principles for banks
    url: https://www.bankofengland.co.uk/...
    licence: ...
    ---

Chunking: split on markdown headings, then long sections into ~1200-character windows on paragraph
boundaries. ``chunk_id = "<file stem>#<n>"`` (stable while the file is unchanged; documents cite it as
``kb:<chunk_id>``); ``locator`` = file, heading path and line range.

Retrieval: TF-IDF vectors (unigrams + bigrams, sublinear tf, smoothed idf), L2-normalised, ranked by inner
product (= cosine). FAISS ``IndexFlatIP`` is used when installed (``uv sync --extra rag``), numpy otherwise -
same results. No embedding API is needed, so it runs offline in CI and in the container (which does not
install the ``rag`` extra). The index is rebuilt automatically when a file under ``kb/`` changes.
"""

from __future__ import annotations

import itertools
import logging
import math
import os
import re
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from mrf.config import REPO_ROOT

log = logging.getLogger(__name__)

COLLECTIONS = ("ss1_23", "templates", "mapping")
SUFFIXES = (".md", ".txt")
MAX_CHARS = 1200

_HEADING = re.compile(r"^(#{1,4})\s+(.+?)\s*#*\s*$")
_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    """a an and are as at be been being but by can could do does for from had has have how in into is it its
    may might must no not of on or our shall should so such than that the their them then there these they
    this those to was were what when where which while who will with would you your each other any all also
    if""".split()
)


def kb_dir() -> Path:
    """``MRF_KB_DIR`` (tests, alternative KBs) or ``<repo>/kb``."""
    return Path(os.environ.get("MRF_KB_DIR") or REPO_ROOT / "kb")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    collection: str
    text: str
    source: str
    locator: str
    url: str | None = None

    def to_result(self, score: float) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "source": self.source,
            "locator": self.locator,
            "score": round(score, 4),
            "collection": self.collection,
            "url": self.url,
        }


# ---------------------------------------------------------------------------------------------- loading
def parse_front_matter(text: str) -> tuple[dict[str, str], str, int]:
    """(metadata, body, number of lines consumed by the front-matter)."""
    if not text.startswith("---"):
        return {}, text, 0
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text, 0
    meta: dict[str, str] = {}
    for line in text[3:end].strip().splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip():
            meta[key.strip().lower()] = value.strip().strip("'\"")
    rest = text[end + 4 :]
    newline = rest.find("\n")
    body = rest[newline + 1 :] if newline != -1 else ""
    return meta, body, text[: len(text) - len(body)].count("\n")


def split_sections(body: str, first_line: int = 1) -> list[tuple[list[str], str, int, int]]:
    """Markdown body -> [(heading path, text, start line, end line)], long sections split on paragraphs."""
    sections: list[tuple[list[str], list[str], int]] = []
    stack: list[tuple[int, str]] = []
    current: list[str] = []
    start = first_line
    for offset, line in enumerate(body.split("\n")):
        m = _HEADING.match(line)
        if m:
            sections.append(([h for _, h in stack], current, start))
            level = len(m.group(1))
            stack = [(lvl, h) for lvl, h in stack if lvl < level] + [(level, m.group(2).strip())]
            current, start = [], first_line + offset + 1
        else:
            current.append(line)
    sections.append(([h for _, h in stack], current, start))

    out: list[tuple[list[str], str, int, int]] = []
    for path, lines, line_start in sections:
        window: list[int] = []  # indices into ``lines``
        for i, line in enumerate(lines):
            window.append(i)
            size = sum(len(lines[j]) + 1 for j in window)
            if (line.strip() == "" and size >= MAX_CHARS) or i == len(lines) - 1:
                filled = [j for j in window if lines[j].strip()]
                if filled:
                    text = "\n".join(lines[filled[0] : filled[-1] + 1])
                    out.append((path, text, line_start + filled[0], line_start + filled[-1]))
                window = []
    return out


def load_chunks(root: Path | None = None) -> list[Chunk]:
    root = root or kb_dir()
    chunks: list[Chunk] = []
    seen_stems: set[str] = set()
    for collection in COLLECTIONS:
        folder = root / collection
        if not folder.is_dir():
            continue
        for path in sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in SUFFIXES):
            text = path.read_text(encoding="utf-8", errors="replace")
            meta, body, consumed = parse_front_matter(text)
            stem = path.stem if path.stem not in seen_stems else f"{collection}.{path.stem}"
            seen_stems.add(stem)
            rel = path.relative_to(root).as_posix()
            for n, (heading_path, body_text, a, b) in enumerate(split_sections(body, consumed + 1), start=1):
                title = heading_path[-1] if heading_path else path.stem
                chunks.append(
                    Chunk(
                        chunk_id=f"{stem}#{n}",
                        collection=collection,
                        text=f"{title}\n{body_text}" if heading_path else body_text,
                        source=meta.get("source") or rel,
                        locator=f"kb/{rel} > {' > '.join(heading_path) or '(top)'} (lines {a}-{b})",
                        url=meta.get("url"),
                    )
                )
    return chunks


# ---------------------------------------------------------------------------------------------- retrieval
def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def terms(text: str) -> list[str]:
    words = [_stem(t) for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]
    return words + [f"{a}_{b}" for a, b in itertools.pairwise(words)]


class KnowledgeBase:
    """In-memory TF-IDF index over the knowledge-base chunks."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self._by_id = {c.chunk_id: c for c in chunks}
        docs = [terms(f"{c.locator} {c.text}") for c in chunks]
        df = Counter(t for d in docs for t in set(d))
        vocab = sorted(df)
        self.vocab = {t: i for i, t in enumerate(vocab)}
        n = len(docs)
        self.idf = np.array([math.log((1 + n) / (1 + df[t])) + 1.0 for t in vocab], dtype=np.float32)
        self.matrix = (
            np.vstack([self._vector(d) for d in docs]) if docs else np.zeros((0, 0), dtype=np.float32)
        )
        self._faiss = self._faiss_index()

    @property
    def backend(self) -> str:
        return "faiss" if self._faiss is not None else "numpy"

    def _faiss_index(self) -> Any:
        if not self.chunks:
            return None
        try:
            import faiss
        except ImportError:
            return None
        index = faiss.IndexFlatIP(self.matrix.shape[1])
        index.add(np.ascontiguousarray(self.matrix))
        return index

    def _vector(self, doc_terms: list[str]) -> np.ndarray:
        vec = np.zeros(len(self.vocab), dtype=np.float32)
        for term, count in Counter(doc_terms).items():
            i = self.vocab.get(term)
            if i is not None:
                vec[i] = (1.0 + math.log(count)) * self.idf[i]
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm else vec

    def get(self, chunk_id: str) -> Chunk | None:
        return self._by_id.get(chunk_id.removeprefix("kb:"))

    def search(self, query: str, top_k: int = 5, collection: str | None = None) -> list[dict[str, Any]]:
        if not self.chunks:
            return []
        q = self._vector(terms(query))
        if not q.any():
            return []
        if self._faiss is not None:
            scores, idx = self._faiss.search(q[None, :], len(self.chunks))
            ranked = list(zip(idx[0].tolist(), scores[0].tolist(), strict=True))
        else:
            sims = self.matrix @ q
            order = np.argsort(-sims, kind="stable")
            ranked = [(int(i), float(sims[i])) for i in order]
        results: list[dict[str, Any]] = []
        for i, score in ranked:
            if i < 0 or score <= 0:
                break
            chunk = self.chunks[i]
            if collection and chunk.collection != collection:
                continue
            results.append(chunk.to_result(score))
            if len(results) >= top_k:
                break
        return results


_lock = threading.Lock()
_cache: tuple[tuple[Any, ...], KnowledgeBase] | None = None


def _signature(root: Path) -> tuple[Any, ...]:
    files = sorted(p for c in COLLECTIONS if (root / c).is_dir() for p in (root / c).rglob("*") if p.is_file())
    return (str(root), *((p.as_posix(), p.stat().st_mtime_ns, p.stat().st_size) for p in files))


def get_kb(root: Path | None = None) -> KnowledgeBase:
    """Process-wide knowledge base; rebuilt when any source file changes."""
    global _cache
    root = root or kb_dir()
    sig = _signature(root)
    with _lock:
        if _cache is None or _cache[0] != sig:
            kb = KnowledgeBase(load_chunks(root))
            log.info("knowledge base: %d chunks from %s (%s)", len(kb.chunks), root, kb.backend)
            _cache = (sig, kb)
        return _cache[1]
