"""Persistence. Owner: A1.

    from mrf.storage import Collections, get_blobs, get_repo
    repo = get_repo()
    await repo.put(Collections.DOCUMENTS, doc.doc_id, doc)
    doc = await repo.get(Collections.DOCUMENTS, doc_id, Document)          # missing -> MRF-1404
    page = await repo.find(Collections.RATINGS, Rating, where={"doc_id": doc_id}, order_by="attempt")
    ref = await get_blobs().put_bytes(f"rebuilds/{rb_id}/model.py", code.encode(), media_type="text/x-python")

Backends (MRF_STORAGE_BACKEND): ``sqlite`` (default, file at MRF_SQLITE_PATH), ``memory`` (tests),
``cosmos`` (cloud, 11/9). Blobs: local dir ``MRF_DATA_DIR/blobs`` (Azure Blob in cloud, 11/9).
Never talk to SQL / Cosmos directly from other modules.
"""

from __future__ import annotations

from mrf.config import get_settings
from mrf.storage.base import BlobStore, Collections, Page, Pagination, Repository
from mrf.storage.blobs import LocalBlobStore
from mrf.storage.memory import MemoryRepository
from mrf.storage.sqlite import SqliteRepository

__all__ = [
    "BlobStore",
    "Collections",
    "LocalBlobStore",
    "MemoryRepository",
    "Page",
    "Pagination",
    "Repository",
    "SqliteRepository",
    "get_blobs",
    "get_repo",
    "set_blobs",
    "set_repo",
]

_repo: Repository | None = None
_blobs: BlobStore | None = None


def get_repo() -> Repository:
    global _repo
    if _repo is None:
        s = get_settings()
        backend = s.storage_backend
        if backend == "memory":
            _repo = MemoryRepository()
        elif backend == "sqlite":
            _repo = SqliteRepository(s.sqlite_path)
        else:
            raise NotImplementedError("cosmos repository lands 11/9 (A1); use MRF_STORAGE_BACKEND=sqlite")
    return _repo


def set_repo(repo: Repository | None) -> None:
    """Swap the process-wide repository (tests)."""
    global _repo
    _repo = repo


def get_blobs() -> BlobStore:
    global _blobs
    if _blobs is None:
        s = get_settings()
        if s.blob_account_url:
            raise NotImplementedError("Azure Blob store lands 11/9 (A1); leave MRF_BLOB_ACCOUNT_URL empty")
        _blobs = LocalBlobStore(s.data_dir / "blobs")
    return _blobs


def set_blobs(blobs: BlobStore | None) -> None:
    global _blobs
    _blobs = blobs
