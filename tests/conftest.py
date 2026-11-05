"""Shared fixtures. CI always runs with MRF_LLM_PROVIDER=mock and in-memory storage (no network, no files)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

os.environ["MRF_LLM_PROVIDER"] = "mock"
os.environ["MRF_STORAGE_BACKEND"] = "memory"
os.environ["MRF_ENV"] = "local"
os.environ["MRF_API_KEY"] = "test-key"

import pytest

from mrf import jobs, llm, storage
from mrf.config import get_settings
from mrf.orchestrator import service


@pytest.fixture(autouse=True)
def _fresh_singletons(tmp_path: Path) -> Iterator[None]:
    """Every test gets its own repo, blob dir, LLM mock, executor and orchestrator."""
    get_settings.cache_clear()
    os.environ["MRF_DATA_DIR"] = str(tmp_path)
    storage.set_repo(storage.MemoryRepository())
    storage.set_blobs(storage.LocalBlobStore(tmp_path / "blobs"))
    llm.set_llm(None)
    jobs.set_executor(None)
    service.set_orchestrator(None)
    yield
    get_settings.cache_clear()


API_HEADERS = {"X-API-Key": "test-key"}
