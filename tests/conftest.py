"""Shared fixtures. CI always runs with MRF_LLM_PROVIDER=mock (no network)."""

from __future__ import annotations

import os

os.environ.setdefault("MRF_LLM_PROVIDER", "mock")
os.environ.setdefault("MRF_STORAGE_BACKEND", "sqlite")
