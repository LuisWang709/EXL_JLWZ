"""Per-batch data quality - implements ``DataQualityChecker`` (slot ``quality_checker``). Owner: A4.

Checks, in order:
    row_count        0 rows -> red; fewer than ``min_rows`` -> amber
    columns_present  columns declared on the Dataset but missing from the file -> red
    missing_rate     worst column above ``missing_rate_red`` -> red, above ``missing_rate_amber`` -> amber
    schema           A2's pandera schema (``Dataset.schema_name``) - value ranges and allowed codes live there -> red

``passed`` is False when any check is red. Per the contract, a red report does not raise here: A2's ModelRunner
refuses the run with MRF-3101, and the monitoring batch (mrf.monitoring.batch) does the same.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal

from mrf.contracts.models import Dataset, QualityCheck, QualityReport
from mrf.monitoring.drift import thresholds
from mrf.monitoring.frames import load_frame
from mrf.storage import Collections, get_repo

if TYPE_CHECKING:
    import pandas as pd

MAX_FAILURE_EXAMPLES = 10
Severity = Literal["info", "amber", "red"]


def _row_count(df: pd.DataFrame, policy: dict[str, Any]) -> QualityCheck:
    rows, minimum = len(df), int(policy["min_rows"])
    severity: Severity = "red" if rows == 0 else ("amber" if rows < minimum else "info")
    return QualityCheck(name="row_count", passed=severity != "red", severity=severity, value=rows, threshold=minimum)


def _columns_present(ds: Dataset, df: pd.DataFrame) -> QualityCheck | None:
    declared = [c.name for c in ds.columns]
    if not declared:
        return None
    missing = [c for c in declared if c not in df.columns]
    return QualityCheck(
        name="columns_present",
        passed=not missing,
        severity="red" if missing else "info",
        value=len(declared) - len(missing),
        threshold=len(declared),
        detail={"missing": missing},
    )


def _missing_rate(df: pd.DataFrame, policy: dict[str, Any]) -> QualityCheck:
    amber, red = float(policy["missing_rate_amber"]), float(policy["missing_rate_red"])
    rates = {str(c): round(float(v), 6) for c, v in df.isna().mean().items()} if len(df) else {}
    worst = max(rates.values(), default=0.0)
    severity: Severity = "red" if worst > red else ("amber" if worst > amber else "info")
    return QualityCheck(
        name="missing_rate",
        passed=severity != "red",
        severity=severity,
        value=worst,
        threshold=amber,
        detail={"by_column": rates, "red_threshold": red},
    )


def _schema(name: str, df: pd.DataFrame) -> QualityCheck:
    from mrf.data import validate

    try:
        validate(name, df, lazy=True)
    except KeyError as exc:  # schema not registered by A2
        return QualityCheck(name="schema", passed=False, severity="red", value=name, detail={"error": str(exc)})
    except Exception as exc:  # pandera SchemaErrors / SchemaError
        cases = getattr(exc, "failure_cases", None)
        examples: list[dict[str, Any]] = []
        n_failures: int | None = None
        if cases is not None:
            n_failures = len(cases)
            cols = [c for c in ("column", "check", "failure_case", "index") if c in cases.columns]
            examples = cases[cols].head(MAX_FAILURE_EXAMPLES).astype(str).to_dict(orient="records")
        return QualityCheck(
            name="schema",
            passed=False,
            severity="red",
            value=name,
            threshold=n_failures,
            detail={"n_failures": n_failures, "examples": examples, "error": str(exc).splitlines()[0][:300]},
        )
    return QualityCheck(name="schema", passed=True, severity="info", value=name)


def run_checks(ds: Dataset, df: pd.DataFrame, policy: dict[str, Any] | None = None) -> list[QualityCheck]:
    policy = policy or thresholds()
    checks = [_row_count(df, policy)]
    present = _columns_present(ds, df)
    if present is not None:
        checks.append(present)
    checks.append(_missing_rate(df, policy))
    if ds.schema_name:
        checks.append(_schema(ds.schema_name, df))
    return checks


class QualityCheckerImpl:
    async def check(self, dataset_id: str) -> QualityReport:
        repo = get_repo()
        ds = await repo.get(Collections.DATASETS, dataset_id, Dataset)  # missing -> MRF-1404
        try:
            df = await asyncio.to_thread(load_frame, ds)
        except Exception as exc:  # unreadable file is a quality failure, not a crash
            checks = [
                QualityCheck(
                    name="readable",
                    passed=False,
                    severity="red",
                    value=ds.uri,
                    detail={"error": f"{type(exc).__name__}: {exc}"[:300]},
                )
            ]
        else:
            checks = await asyncio.to_thread(run_checks, ds, df)
        report = QualityReport(dataset_id=dataset_id, passed=all(c.severity != "red" for c in checks), checks=checks)
        await repo.put(Collections.QUALITY, dataset_id, report)
        return report
