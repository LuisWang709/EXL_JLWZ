"""Blob stores: local filesystem (local/CI) and Azure Blob (cloud, A1 11/9)."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from mrf.contracts.models import ArtifactRef
from mrf.core import MRFCode, MRFError


def _safe_rel(path: str) -> PurePosixPath:
    rel = PurePosixPath(path.replace("\\", "/").lstrip("/"))
    if any(part in {"..", ""} for part in rel.parts) or not rel.parts:
        raise MRFError(MRFCode.INPUT_BODY, f"invalid blob path {path!r}")
    return rel


class LocalBlobStore:
    """Files under ``root``; uris are ``file:///abs/path``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def _resolve(self, uri: str) -> Path:
        if uri.startswith("file://"):
            parsed = urlparse(uri)
            raw = unquote(parsed.path)
            if len(raw) > 2 and raw[0] == "/" and raw[2] == ":":  # file:///C:/...
                raw = raw[1:]
            p = Path(raw).resolve()
        else:
            p = (self.root / _safe_rel(uri)).resolve()
        if self.root not in p.parents and p != self.root:
            raise MRFError(MRFCode.INPUT_BODY, "blob uri outside the store root")
        return p

    async def put_bytes(
        self, path: str, data: bytes, *, media_type: str = "application/octet-stream", filename: str | None = None
    ) -> ArtifactRef:
        target = (self.root / _safe_rel(path)).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_bytes, data)
        return ArtifactRef(
            uri=target.as_uri(),
            filename=filename or target.name,
            media_type=media_type,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
        )

    async def get_bytes(self, uri: str) -> bytes:
        p = self._resolve(uri)
        if not p.is_file():
            raise MRFError(MRFCode.NOT_FOUND, f"blob {uri} not found")
        return await asyncio.to_thread(p.read_bytes)

    async def exists(self, uri: str) -> bool:
        try:
            return self._resolve(uri).is_file()
        except MRFError:
            return False

    def local_path(self, uri: str) -> Path:
        """Filesystem path for tools that need one (pandas/pyreadstat readers, sandbox mounts)."""
        return self._resolve(uri)
