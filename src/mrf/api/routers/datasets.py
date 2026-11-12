"""Dataset registration and quality.

Owner: A2 (register) / A4 (quality). Endpoints (see openapi.yaml for request/response schemas):
    POST /api/v1/datasets                          201  register a dataset (JSON reference or multipart upload)
    GET  /api/v1/datasets                          200  list datasets (paged; filter by model_id / role)
    GET  /api/v1/datasets/{dataset_id}             200  dataset metadata
    GET  /api/v1/datasets/{dataset_id}/quality     200  data quality checks (A4)

Two ways to register (additive to contract v1):

* ``application/json`` ``DatasetCreate`` - ``uri`` must point at a file already in our blob store;
* ``multipart/form-data`` - ``file`` plus the same fields as form values; the file is stored and screened.

Either way the file is read once: an unreadable file is refused (MRF-1003) and ``row_count`` / ``columns`` are
filled from the data.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import PurePosixPath
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from mrf.api.deps import Paging, created, ok, paged
from mrf.config import get_settings
from mrf.contracts.models import ColumnInfo, Dataset, DatasetFormat, ModelRecord, QualityReport
from mrf.core import MRFCode, MRFError, guards
from mrf.core.ids import new_id
from mrf.storage import Collections, get_blobs, get_repo

router = APIRouter(prefix="/datasets", tags=["datasets"])

Role = Literal["development", "out_of_time", "validation", "monitoring_batch", "reference", "other"]
DATA_SUFFIXES = {".csv", ".tsv", ".txt", ".parquet", ".pq", ".feather", ".xlsx", ".xls", ".json", ".jsonl"}
TEXT_SUFFIXES = {".csv", ".tsv", ".txt", ".json", ".jsonl"}
_ROLE_HINTS = {"target": "target", "default_flag": "target", "id": "id", "score": "score"}


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    uri: str = Field(min_length=1)
    format: DatasetFormat | None = None
    role: Role = "other"
    model_id: str | None = None
    schema_name: str | None = None
    columns: list[ColumnInfo] = Field(default_factory=list)
    read_options: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _describe(dataset: Dataset) -> tuple[int, list[ColumnInfo]]:
    from mrf.monitoring.frames import load_frame

    frame = load_frame(dataset)
    columns = [
        ColumnInfo(
            name=str(c),
            dtype=str(frame[c].dtype),
            role=_ROLE_HINTS.get(str(c).lower(), "feature"),  # type: ignore[arg-type]
            nullable=bool(frame[c].isna().any()),
        )
        for c in frame.columns
    ]
    return len(frame), columns


async def _register(body: DatasetCreate) -> Dataset:
    from mrf.data import infer_format
    from mrf.data.schemas import SCHEMAS

    repo = get_repo()
    if body.model_id:
        await repo.get(Collections.MODELS, body.model_id, ModelRecord)
    if body.schema_name and body.schema_name not in SCHEMAS:
        raise MRFError(
            MRFCode.INPUT_BODY,
            f"unknown schema_name '{body.schema_name}'",
            field="schema_name",
            detail={"registered": sorted(SCHEMAS)},
        )
    if not await get_blobs().exists(body.uri):
        raise MRFError(
            MRFCode.INPUT_BODY, "uri must point at a file in the blob store (upload it instead)", field="uri"
        )
    fmt = body.format or infer_format(body.uri)
    dataset = Dataset(dataset_id=new_id("dataset"), **{**body.model_dump(exclude={"format"}), "format": fmt})
    try:
        row_count, columns = await asyncio.to_thread(_describe, dataset)
    except MRFError:
        raise
    except Exception as exc:
        raise MRFError(
            MRFCode.INPUT_DATA_SCHEMA,
            f"the file could not be read as {fmt.value}: {type(exc).__name__}",
            field="uri",
        ) from exc
    dataset.row_count = row_count
    if not dataset.columns:
        dataset.columns = columns
    await repo.put(Collections.DATASETS, dataset.dataset_id, dataset)
    return dataset


@router.post("", status_code=201, summary="Register a dataset (JSON reference or file upload)")
async def register_dataset(request: Request) -> JSONResponse:
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("application/json"):
        try:
            body = DatasetCreate.model_validate(await request.json())
        except (ValidationError, json.JSONDecodeError) as exc:
            raise MRFError(
                MRFCode.INPUT_BODY, "invalid DatasetCreate body", detail={"errors": str(exc)[:1000]}
            ) from exc
        guards.raise_on(guards.scan_text(body.name, "name"), field="name")
        return created(request, await _register(body))
    if not ctype.startswith("multipart/form-data"):
        raise MRFError(MRFCode.INPUT_BODY, "use application/json (uri) or multipart/form-data (file)")

    form = await request.form()
    upload = form.get("file")
    if upload is None or isinstance(upload, str):
        raise MRFError(MRFCode.INPUT_BODY, "file is required", field="file")
    filename = PurePosixPath(upload.filename or "dataset.csv").name
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in DATA_SUFFIXES:
        raise MRFError(
            MRFCode.INPUT_FILE_TYPE,
            f"'{filename}': {suffix or 'no suffix'} not allowed",
            field="file",
            detail={"allowed": sorted(DATA_SUFFIXES)},
        )
    data = await upload.read()
    if len(data) > get_settings().max_upload_mb * 1024 * 1024:
        raise MRFError(MRFCode.INPUT_FILE_SIZE, f"'{filename}' exceeds {get_settings().max_upload_mb} MB", field="file")
    name = str(form.get("name") or filename).strip()
    findings = guards.scan_text(name, "name")
    if suffix in TEXT_SUFFIXES:  # binary formats cannot be pattern-scanned; the schema check still applies
        findings += guards.scan_file(filename if suffix != ".txt" else filename + ".csv", data)
    guards.raise_on(findings, field="file")
    try:
        fields = DatasetCreate(
            name=name,
            uri="pending",
            role=str(form.get("role") or "other"),  # type: ignore[arg-type]
            model_id=str(form.get("model_id") or "") or None,
            schema_name=str(form.get("schema_name") or "") or None,
            read_options=json.loads(str(form.get("read_options") or "{}")),
            metadata=json.loads(str(form.get("metadata") or "{}")),
        )
    except (ValidationError, json.JSONDecodeError) as exc:
        raise MRFError(MRFCode.INPUT_BODY, "invalid dataset fields", detail={"errors": str(exc)[:1000]}) from exc
    ref = await get_blobs().put_bytes(f"datasets/{new_id('dataset')}/{filename}", data, filename=filename)
    return created(request, await _register(fields.model_copy(update={"uri": ref.uri})))


@router.get("", summary="List datasets")
async def list_datasets(
    request: Request, paging: Paging, model_id: str | None = None, role: Role | None = None
) -> JSONResponse:
    where = {k: v for k, v in (("model_id", model_id), ("role", role)) if v}
    page = await get_repo().find(
        Collections.DATASETS, Dataset, where=where or None, page=paging.page, page_size=paging.page_size
    )
    return paged(request, page)


@router.get("/{dataset_id}", summary="Dataset metadata")
async def get_dataset(dataset_id: str, request: Request) -> JSONResponse:
    return ok(request, await get_repo().get(Collections.DATASETS, dataset_id, Dataset))


# ---------------------------------------------------------------- A4: quality
@router.get("/{dataset_id}/quality")
async def get_dataset_quality(dataset_id: str, request: Request) -> JSONResponse:
    """Latest quality report; runs the checks now if the dataset was never checked (unknown id -> MRF-1404)."""
    from mrf.monitoring.quality import QualityCheckerImpl

    report = await get_repo().get_or_none(Collections.QUALITY, dataset_id, QualityReport)
    if report is None:
        report = await QualityCheckerImpl().check(dataset_id)
    return ok(request, report)
