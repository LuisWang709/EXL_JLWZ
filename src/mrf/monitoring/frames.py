"""Load a registered Dataset into pandas (thin wrapper over A2's mrf.data.read_any). Owner: A4."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

from mrf.contracts.models import Dataset, DatasetFormat, Run

if TYPE_CHECKING:
    import pandas as pd

#: column names accepted as "the model score" in a runner output file, in order of preference
SCORE_COLUMNS = ("score", "pd", "pd_python", "prediction", "probability")


def _local_uri(uri: str) -> str:
    if not uri.startswith("file://"):
        return uri
    path = unquote(urlparse(uri).path)
    if len(path) > 2 and path[0] == "/" and path[2] == ":":  # file:///C:/... on Windows
        path = path[1:]
    return path


def load_frame(ds: Dataset) -> pd.DataFrame:
    """Read a dataset; ``format=other`` falls back to the uri suffix (Dataset.format defaults to ``other``)."""
    from mrf.data import infer_format, read_any

    update: dict[str, Any] = {"uri": _local_uri(ds.uri)}
    if ds.format == DatasetFormat.OTHER:
        update["format"] = infer_format(ds.uri)
    return read_any(ds.model_copy(update=update))


def run_scores(run: Run | None) -> pd.Series | None:
    """Scores written by the runner (an output csv/parquet with a score column), or None if there are none."""
    if run is None:
        return None
    import pandas as pd

    for art in run.outputs:
        path = _local_uri(art.uri)
        name = art.filename.lower()
        if name.endswith(".parquet"):
            df = pd.read_parquet(path)
        elif name.endswith(".csv"):
            df = pd.read_csv(path)
        else:
            continue
        for col in SCORE_COLUMNS:
            if col in df.columns:
                return df[col]
    return None
