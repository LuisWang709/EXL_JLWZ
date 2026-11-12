"""Operation snapshots reuse file reads across quality/scoring workers and expire between batches."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from mrf.monitoring.frames import frame_scope, load_frame
from tests.unit.monitoring_helpers import add_dataset, frame


async def test_nested_thread_snapshots_read_once_and_expire(tmp_path: Path) -> None:
    ds = await add_dataset(tmp_path, "snap", frame())
    with patch("mrf.monitoring.frames._read_frame", wraps=lambda ds: pd.read_csv(ds.uri)) as read:
        with frame_scope():
            with frame_scope():
                first, second = await asyncio.gather(
                    asyncio.to_thread(load_frame, ds), asyncio.to_thread(load_frame, ds),
                )
            assert first is second and read.call_count == 1
            changed_options = ds.model_copy(update={"read_options": {"encoding": "utf-8"}})
            load_frame(changed_options)
            assert read.call_count == 2  # reader options are part of the snapshot identity
        frame(n=201).to_csv(ds.uri, index=False)
        with frame_scope():
            assert len(load_frame(ds)) == 201
            assert read.call_count == 3
