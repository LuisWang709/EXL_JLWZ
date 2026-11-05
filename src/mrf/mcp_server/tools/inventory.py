"""Owner: A1."""

from __future__ import annotations

from typing import Any


async def parse_code(file_uri: str, language_hint: str | None = None) -> dict[str, Any]:
    """Statically parse one SAS / R / Python model source file (no execution).

    Args:
        file_uri: stored artefact uri of the source file.
        language_hint: 'sas' | 'r' | 'python' | None (auto-detect).

    Returns:
        {"language": str, "procedures": [str], "target": str | None, "features": [str],
         "statements": [{"kind": str, "line_start": int, "line_end": int, "text": str}],
         "datasets_referenced": [str], "warnings": [str]}
    Raises MRF-2001 when the file cannot be parsed at all.
    """
    raise NotImplementedError


async def get_inventory(model_id: str | None = None) -> dict[str, Any]:
    """Read the model inventory. With ``model_id`` -> {"model": ModelRecord};
    without -> {"models": [ModelRecord]}. Read-only."""
    raise NotImplementedError
