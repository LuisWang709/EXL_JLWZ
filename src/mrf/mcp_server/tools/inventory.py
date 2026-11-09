"""Owner: A1."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse

from mrf.contracts.models import ModelRecord
from mrf.core import MRFCode, MRFError
from mrf.storage import Collections, get_blobs, get_repo


async def parse_code(file_uri: str, language_hint: str | None = None) -> dict[str, Any]:
    """Statically parse one SAS / R / Python model source file (no execution).

    Args:
        file_uri: stored artefact uri of the source file.
        language_hint: 'sas' | 'r' | 'python' | None (auto-detect).

    Returns:
        {"language": str, "procedures": [str], "algorithm": str, "target": str | None, "features": [str],
         "class_variables": {name: reference_level}, "purpose_hint": str | None,
         "statements": [{"kind": str, "line_start": int, "line_end": int, "text": str}],
         "datasets_referenced": [str], "warnings": [str], "filename": str}
    Raises MRF-2001 when the file cannot be parsed at all.
    """
    from mrf.agents.classify.parsers import parse_source

    raw = await get_blobs().get_bytes(file_uri)
    filename = PurePosixPath(unquote(urlparse(file_uri).path) or file_uri).name
    try:
        parsed = parse_source(filename, raw, language_hint)
    except ValueError as exc:
        raise MRFError(MRFCode.CODE_UNPARSEABLE, f"{filename}: {exc}", field="file_uri") from exc
    if parsed.language == "unknown" and not parsed.statements:
        raise MRFError(MRFCode.CODE_UNPARSEABLE, f"{filename}: language could not be detected", field="file_uri")
    return parsed.to_dict()


async def get_inventory(model_id: str | None = None) -> dict[str, Any]:
    """Read the model inventory. With ``model_id`` -> {"model": ModelRecord};
    without -> {"models": [ModelRecord]}. Read-only."""
    repo = get_repo()
    if model_id:
        model = await repo.get(Collections.MODELS, model_id, ModelRecord)
        return {"model": model.model_dump(mode="json")}
    page = await repo.find(Collections.MODELS, ModelRecord, page_size=500)
    return {"models": [m.model_dump(mode="json") for m in page.items]}
