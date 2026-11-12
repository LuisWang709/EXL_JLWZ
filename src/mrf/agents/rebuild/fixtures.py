"""Parity fixtures: the legacy model's exported evidence that a rebuild is checked against.

A fixture is a directory with

    manifest.json        {"model_id", "record_id_column", "score_column", "link"?, ...}
    input_sample.csv     records the legacy system scored
    legacy_scores.csv    record id + legacy score (the ground truth)
    coefficients.json    legacy parameter estimates: {"intercept": .., "<term>": ..}

It is found in this order:

1. files uploaded with the pipeline (the "legacy model package") - staged under ``<data_dir>/fixtures/<model_id>``;
2. an explicit fixture id (API ``fixture_id`` or model tag ``fixture_id``);
3. a built-in fixture whose id (``m001`` ...) appears in the model name or a source file name.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from mrf.config import REPO_ROOT, get_settings
from mrf.contracts.models import ArtifactRef, ModelRecord
from mrf.core import MRFCode, MRFError
from mrf.storage import get_blobs

FIXTURE_FILES = ("manifest.json", "input_sample.csv", "legacy_scores.csv", "coefficients.json")
REQUIRED_FILES = ("manifest.json", "input_sample.csv", "legacy_scores.csv")
_FIXTURE_ID = re.compile(r"(?<![a-z0-9])(m\d{3})(?![0-9])", re.IGNORECASE)
_SAFE_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def builtin_root() -> Path:
    return REPO_ROOT / "tests" / "fixtures"


def staged_root() -> Path:
    return Path(get_settings().data_dir).resolve() / "fixtures"


def fixture_dir(fixture_id: str) -> Path | None:
    """Directory of a fixture id: staged (uploaded) first, then built-in. None when unknown."""
    if not _SAFE_ID.match(fixture_id):
        raise MRFError(
            MRFCode.INPUT_BODY, "fixture_id may only contain letters, digits, '_' and '-'", field="fixture_id"
        )
    for root in (staged_root(), builtin_root()):
        for name in (fixture_id, fixture_id.lower()):
            candidate = root / name
            if (candidate / "manifest.json").is_file():
                return candidate
    return None


@dataclass
class Fixture:
    fixture_id: str
    path: Path
    manifest: dict[str, Any]
    coefficients: dict[str, float]

    @property
    def id_column(self) -> str:
        return str(self.manifest.get("record_id_column", "id"))

    @property
    def score_column(self) -> str:
        return str(self.manifest.get("score_column", "pd_legacy"))

    @property
    def link(self) -> str:
        return str(self.manifest.get("link", "logit")).lower()


def load_fixture(fixture_id: str) -> Fixture:
    path = fixture_dir(fixture_id)
    if path is None:
        raise MRFError(MRFCode.NOT_FOUND, f"parity fixture '{fixture_id}' not found", field="fixture_id")
    missing = [f for f in REQUIRED_FILES if not (path / f).is_file()]
    if missing:
        raise MRFError(MRFCode.NOT_FOUND, f"parity fixture '{fixture_id}' is incomplete: {missing}", field="fixture_id")
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    coef_path = path / "coefficients.json"
    coefficients = json.loads(coef_path.read_text(encoding="utf-8")) if coef_path.is_file() else {}
    return Fixture(fixture_id, path, manifest, {str(k): float(v) for k, v in coefficients.items()})


async def _stage_uploaded(model_id: str, files: list[ArtifactRef]) -> str | None:
    """Copy an uploaded legacy model package into the staged fixture directory."""
    by_name = {PurePosixPath(f.filename).name.lower(): f for f in files}
    if not all(name in by_name for name in REQUIRED_FILES):
        return None
    target = staged_root() / model_id
    target.mkdir(parents=True, exist_ok=True)
    blobs = get_blobs()
    for name in FIXTURE_FILES:
        if name in by_name:
            (target / name).write_bytes(await blobs.get_bytes(by_name[name].uri))
    return model_id


async def resolve_fixture(model: ModelRecord, files: list[ArtifactRef], explicit: str | None = None) -> str | None:
    """Fixture id for a model, or None when there is nothing to prove parity against."""
    if explicit is not None and fixture_dir(explicit) is None:
        raise MRFError(MRFCode.NOT_FOUND, f"parity fixture '{explicit}' not found", field="fixture_id")
    staged = await _stage_uploaded(model.model_id, files)
    if staged:
        return staged
    for candidate in (explicit, model.tags.get("fixture_id")):
        if candidate and fixture_dir(candidate) is not None:
            return candidate
    for text in (model.name, *(f.filename for f in files)):
        m = _FIXTURE_ID.search(text or "")
        if m and fixture_dir(m.group(1).lower()) is not None:
            return m.group(1).lower()
    return None
