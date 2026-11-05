"""Prefixed, sortable-enough IDs: ``pl_``, ``job_``, ``mdl_`` ... (prefix tells you the resource)."""

from __future__ import annotations

import secrets
import time
import uuid

PREFIXES = {
    "pipeline": "pl",
    "job": "job",
    "model": "mdl",
    "document": "doc",
    "rating": "rat",
    "rebuild": "rb",
    "dataset": "ds",
    "run": "run",
    "report": "rpt",
    "review": "rev",
    "alert": "alr",
}


def new_id(kind: str) -> str:
    prefix = PREFIXES[kind]
    return f"{prefix}_{int(time.time()):x}{secrets.token_hex(4)}"


def new_request_id() -> str:
    return str(uuid.uuid4())
