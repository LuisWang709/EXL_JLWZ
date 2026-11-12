"""Azure Blob IO, private URL materialisation and container boundaries without network calls."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mrf.core import MRFCode, MRFError
from mrf.storage.azure_blobs import AzureBlobStore


class Container:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def upload_blob(self, name: str, data: bytes, **kwargs: Any) -> None:
        self.data[name] = data

    def download_blob(self, name: str) -> Any:
        from azure.core.exceptions import ResourceNotFoundError

        if name not in self.data:
            raise ResourceNotFoundError("missing")
        return SimpleNamespace(readall=lambda: self.data[name])

    def get_blob_client(self, name: str) -> Any:
        return SimpleNamespace(exists=lambda: name in self.data)


async def test_roundtrip_and_private_file_reader(tmp_path: Path) -> None:
    from mrf.contracts.models import Dataset
    from mrf.monitoring.frames import load_frame
    from mrf.storage import set_blobs

    blobs = AzureBlobStore("https://example.blob.core.windows.net", "mrf", tmp_path, client=Container())
    ref = await blobs.put_bytes("datasets/a b.csv", b"id,value\n1,3\n", media_type="text/csv")
    assert ref.uri.endswith("a%20b.csv")
    assert ref.sha256 == hashlib.sha256(b"id,value\n1,3\n").hexdigest()
    assert await blobs.exists(ref.uri)
    assert await blobs.get_bytes(ref.uri) == b"id,value\n1,3\n"
    set_blobs(blobs)
    assert load_frame(Dataset(dataset_id="ds", name="test", uri=ref.uri)).iloc[0]["value"] == 3
    await blobs.put_bytes("datasets/a b.csv", b"id,value\n1,7\n")
    assert load_frame(Dataset(dataset_id="ds", name="test", uri=ref.uri)).iloc[0]["value"] == 7
    with pytest.raises(MRFError) as exc:
        await blobs.get_bytes("missing.csv")
    assert exc.value.code is MRFCode.NOT_FOUND


@pytest.mark.parametrize("uri", [
    "../escape.csv", "https://other.example/mrf/a.csv",
    "https://example.blob.core.windows.net/mrf-other/a.csv",
    "https://example.blob.core.windows.net/mrf/%2e%2e/escape.csv",
    "https://example.blob.core.windows.net/mrf/a.csv?secret=value",
])
async def test_refuses_outside_container(tmp_path: Path, uri: str) -> None:
    blobs = AzureBlobStore("https://example.blob.core.windows.net", "mrf", tmp_path, client=Container())
    assert not await blobs.exists(uri)
    with pytest.raises(MRFError):
        await blobs.get_bytes(uri)
