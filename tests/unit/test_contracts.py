from __future__ import annotations

import inspect

from mrf.config import get_policy
from mrf.contracts.models import Dataset, DatasetFormat, Pipeline
from mrf.core import PipelineState
from mrf.data.io import infer_format
from mrf.mcp_server.tools import ALL_TOOLS


def test_policy_loads_and_weights_add_up() -> None:
    p = get_policy()
    assert p["rating"]["rule_weight"] + p["rating"]["llm_weight"] == 100
    assert p["retries"]["doc_quality_max_attempts"] == 3
    assert p["retries"]["parity_max_attempts"] == 5


def test_dataset_accepts_unknown_format_and_metadata() -> None:
    ds = Dataset(dataset_id="ds_1", name="x", uri="blob://x.weird", metadata={"anything": [1, 2]})
    assert ds.format is DatasetFormat.OTHER


def test_infer_format() -> None:
    assert infer_format("a/b/German.CSV") is DatasetFormat.CSV
    assert infer_format("https://acc.blob/x.sas7bdat?sig=1") is DatasetFormat.SAS7BDAT
    assert infer_format("x.jsonl") is DatasetFormat.JSONL
    assert infer_format("no_suffix") is DatasetFormat.OTHER


def test_pipeline_default_state() -> None:
    assert Pipeline(pipeline_id="pl_1", model_id="mdl_1").state is PipelineState.RECEIVED


def test_mcp_tools_are_documented_coroutines() -> None:
    names = {t.__name__ for t in ALL_TOOLS}
    assert names == {
        "parse_code",
        "get_inventory",
        "profile_data",
        "run_sandbox",
        "run_parity",
        "search_kb",
        "compute_metrics",
    }
    for tool in ALL_TOOLS:
        assert inspect.iscoroutinefunction(tool) and tool.__doc__
