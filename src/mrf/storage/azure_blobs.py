"""Managed-identity Azure Blob adapter with a local cache for file-based tools.

The container must already exist and grant the app identity Storage Blob Data Contributor.
Only URLs inside the configured account/container are accepted. The SDK handles retries.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

from mrf.contracts.models import ArtifactRef
from mrf.core import MRFCode, MRFError
from mrf.storage.blobs import _safe_rel


class AzureBlobStore:
    def __init__(self, account_url: str, container: str, cache_dir: Path, *, client: Any = None) -> None:
        parsed = urlparse(account_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("blob account URL must be an HTTPS endpoint without a query or fragment")
        if not container or "/" in container or "\\" in container:
            raise ValueError("invalid blob container")
        self.base_url = account_url.rstrip("/") + "/" + container
        self.cache_dir = cache_dir.resolve()
        if client is None:
            from azure.identity import DefaultAzureCredential
            from azure.storage.blob import BlobServiceClient

            credential = DefaultAzureCredential(managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID"))
            client = BlobServiceClient(account_url, credential=credential).get_container_client(container)
        self.client = client

    def _name(self, uri: str) -> str:
        parsed = urlparse(uri)
        if parsed.scheme or parsed.netloc:
            if not uri.startswith(self.base_url + "/") or parsed.query or parsed.fragment:
                raise MRFError(MRFCode.INPUT_BODY, "blob uri outside the configured container")
            uri = unquote(uri[len(self.base_url) + 1 :])
        return _safe_rel(uri).as_posix()

    def _download(self, uri: str) -> bytes:
        from azure.core.exceptions import ResourceNotFoundError

        name = self._name(uri)
        try:
            return bytes(self.client.download_blob(name).readall())
        except ResourceNotFoundError as exc:
            raise MRFError(MRFCode.NOT_FOUND, "blob not found") from exc

    async def put_bytes(
        self, path: str, data: bytes, *, media_type: str = "application/octet-stream", filename: str | None = None
    ) -> ArtifactRef:
        from azure.storage.blob import ContentSettings

        name = _safe_rel(path).as_posix()
        await asyncio.to_thread(
            self.client.upload_blob,
            name=name,
            data=data,
            overwrite=True,
            content_settings=ContentSettings(content_type=media_type),
        )
        return ArtifactRef(
            uri=self.base_url + "/" + quote(name, safe="/"),
            filename=filename or Path(name).name,
            media_type=media_type,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )

    async def get_bytes(self, uri: str) -> bytes:
        return await asyncio.to_thread(self._download, uri)

    async def exists(self, uri: str) -> bool:
        try:
            name = self._name(uri)
        except MRFError:
            return False
        return bool(await asyncio.to_thread(self.client.get_blob_client(name).exists))

    def local_path(self, uri: str) -> Path:
        """Download a fresh, atomically published snapshot for pandas / sandbox readers."""
        name = self._name(uri)
        data = self._download(uri)
        digest = hashlib.sha256(data).hexdigest()
        target = self.cache_dir / digest / Path(name).name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
                handle.write(data)
                temporary = Path(handle.name)
            try:
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return target
