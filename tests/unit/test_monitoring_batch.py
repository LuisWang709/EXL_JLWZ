"""process_batch / process_pending / MonitoringRegistrarImpl (A4) with fake psi/csi, runner and re-validation."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mrf.contracts.agents import StepContext
from mrf.contracts.models import Alert, ModelRecord, MonitoringMetric, Run, Schedule
from mrf.core import MRFCode, MRFError
from mrf.monitoring.batch import metric_key, process_batch, process_pending
from mrf.monitoring.registrar import TAG_BASELINE_DATASET, TAG_BASELINE_RUN, MonitoringRegistrarImpl
from mrf.storage import Collections, get_repo
from tests.unit.monitoring_helpers import FakeRunner, RevalidationSpy, add_dataset, add_model, frame, install


async def alerts() -> list[Alert]:
    return (await get_repo().find(Collections.ALERTS, Alert, page_size=100)).items


@pytest.fixture
async def seeded(tmp_path: Path) -> Path:
    await add_model()
    await add_dataset(tmp_path, "ds_base", frame(), role="out_of_time")
    return tmp_path


@pytest.mark.parametrize(("shift", "status"), [(0.0, "green"), (0.15, "amber"), (0.40, "red")])
async def test_status_alerts_and_revalidation(
    seeded: Path, monkeypatch: pytest.MonkeyPatch, shift: float, status: str
) -> None:
    runner, spy = FakeRunner(), RevalidationSpy()
    install(monkeypatch, runner, spy)
    await add_dataset(seeded, "ds_m1", frame(shift=shift), role="monitoring_batch", model_id="mdl_t")

    metric = await process_batch("mdl_t", "ds_m1")

    assert metric.status == status and metric.batch_id == "ds_m1" and metric.row_count == 200
    assert set(metric.psi) == {"x1", "x2"}  # id and default_flag are not features
    assert runner.calls == [("ds_m1", "batch", {"reference_dataset_id": "ds_base", "baseline_run_id": None})]
    stored = await alerts()
    assert [a.severity for a in stored] == ([] if status == "green" else [status])
    assert len(spy.calls) == (1 if status == "red" else 0)
    if status == "red":
        assert stored[0].detail["revalidation_job_id"] == "job_reval" and "x1" in spy.calls[0][1]


async def test_gini_drop_vs_baseline_run_is_red(seeded: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = get_repo()
    await repo.put(
        Collections.RUNS,
        "run_base",
        Run(run_id="run_base", model_id="mdl_t", dataset_id="ds_base", metrics={"gini": 0.60}),
    )
    model = await repo.get(Collections.MODELS, "mdl_t", ModelRecord)
    model.tags[TAG_BASELINE_RUN] = "run_base"
    await repo.put(Collections.MODELS, "mdl_t", model)
    install(monkeypatch, FakeRunner(gini=0.50), RevalidationSpy())
    await add_dataset(seeded, "ds_m2", frame(), role="monitoring_batch", model_id="mdl_t")

    metric = await process_batch("mdl_t", "ds_m2")
    assert metric.status == "red" and metric.gini == 0.50


async def test_already_revalidating_does_not_crash(seeded: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = RevalidationSpy(already_running=True)
    install(monkeypatch, FakeRunner(), spy)
    await add_dataset(seeded, "ds_m3", frame(shift=0.5), role="monitoring_batch", model_id="mdl_t")
    metric = await process_batch("mdl_t", "ds_m3")
    assert metric.status == "red" and len(spy.calls) == 1
    assert (await alerts())[0].detail["revalidation_job_id"] is None


async def test_rejected_batch_alerts_once_and_skips_model(seeded: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner, spy = FakeRunner(), RevalidationSpy()
    install(monkeypatch, runner, spy)
    await add_dataset(seeded, "ds_bad", frame(missing=0.5), role="monitoring_batch", model_id="mdl_t")

    with pytest.raises(MRFError) as err:
        await process_batch("mdl_t", "ds_bad")
    assert err.value.code == MRFCode.DATA_QUALITY_FAILED
    assert runner.calls == [] and spy.calls == []
    stored = await alerts()
    assert [(a.kind, a.severity) for a in stored] == [("data_quality", "red")]

    again = await process_batch("mdl_t", "ds_bad")  # recorded: no second alert
    assert again.status == "red" and len(await alerts()) == 1


async def test_same_batch_is_processed_once(seeded: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = FakeRunner()
    install(monkeypatch, runner, RevalidationSpy())
    await add_dataset(seeded, "ds_m4", frame(shift=0.2), role="monitoring_batch", model_id="mdl_t")
    first = await process_batch("mdl_t", "ds_m4")
    second = await process_batch("mdl_t", "ds_m4")
    assert first == second and len(runner.calls) == 1 and len(await alerts()) == 1


async def test_concurrent_requests_do_not_duplicate_scoring_or_alerts(
    seeded: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner()
    install(monkeypatch, runner, RevalidationSpy())
    await add_dataset(seeded, "concurrent", frame(shift=0.2), role="monitoring_batch", model_id="mdl_t")
    first, second = await asyncio.gather(process_batch("mdl_t", "concurrent"), process_batch("mdl_t", "concurrent"))
    assert first == second and len(runner.calls) == 1 and len(await alerts()) == 1


async def test_quality_warning_is_visible_and_does_not_revalidate(
    seeded: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = RevalidationSpy()
    install(monkeypatch, FakeRunner(), spy)
    await add_dataset(seeded, "warning", frame(missing=0.1), role="monitoring_batch", model_id="mdl_t")
    metric = await process_batch("mdl_t", "warning")
    assert metric.status == "amber" and not spy.calls
    assert [(a.kind, a.severity) for a in await alerts()] == [("data_quality", "amber")]


async def test_no_evidence_is_unassessed_and_runner_psi_is_reused(
    seeded: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mrf.monitoring import batch

    class Scored(FakeRunner):
        async def run(self, ctx: StepContext, dataset_id: str, kind: str = "usability") -> Run:
            run = await super().run(ctx, dataset_id, kind)
            run.metrics["psi_score"] = 0.05
            return run

    install(monkeypatch, Scored(), RevalidationSpy())
    monkeypatch.setattr(batch, "pick_features", lambda *args: [])
    monkeypatch.setattr(batch, "run_scores", lambda *args: pytest.fail("runner PSI must not be recalculated"))
    await add_dataset(seeded, "scored", frame(), role="monitoring_batch", model_id="mdl_t")
    assert (await process_batch("mdl_t", "scored")).psi == {"__score__": 0.05}
    install(monkeypatch, FakeRunner(), RevalidationSpy())
    monkeypatch.setattr(batch, "run_scores", lambda *args: None)
    await add_dataset(seeded, "unassessed", frame(), role="monitoring_batch", model_id="mdl_t")
    metric = await process_batch("mdl_t", "unassessed")
    assert metric.status == "amber" and not metric.psi
    assert "unassessed" in (await alerts())[0].message


async def test_pending_red_batch_retries_after_previous_h2(seeded: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = RevalidationSpy(already_running=True)
    install(monkeypatch, FakeRunner(), spy)
    await add_dataset(seeded, "waiting", frame(shift=0.5), role="monitoring_batch", model_id="mdl_t")
    await process_batch("mdl_t", "waiting")
    await get_repo().put(Collections.SCHEDULES, "mdl_t", Schedule(model_id="mdl_t", cron="0 * * * *"))
    spy.already_running = False
    assert (await process_pending())["processed"] == []
    assert (await alerts())[0].detail["revalidation_job_id"] == "job_reval"
    count = len(spy.calls)
    await process_pending()
    assert len(spy.calls) == count


async def test_model_without_baseline_is_invalid_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeRunner(), RevalidationSpy())
    await add_model(baseline=None)
    await add_dataset(tmp_path, "ds_x", frame(), role="monitoring_batch", model_id="mdl_t")
    with pytest.raises(MRFError) as err:
        await process_batch("mdl_t", "ds_x")
    assert err.value.code == MRFCode.INVALID_STATE
    assert [(a.kind, a.severity) for a in await alerts()] == [("system", "red")]
    # A stale baseline tag is also a system fault, detected before invoking the runner.
    await add_model(baseline="missing_dataset")
    with pytest.raises(MRFError, match="baseline dataset missing_dataset is unavailable"):
        await process_batch("mdl_t", "ds_x")


async def test_process_pending_walks_enabled_schedules(seeded: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, FakeRunner(), RevalidationSpy())
    repo = get_repo()
    await repo.put(Collections.SCHEDULES, "mdl_t", Schedule(model_id="mdl_t", cron="0 * * * *"))
    await add_dataset(seeded, "ds_a", frame(), role="monitoring_batch", model_id="mdl_t")
    await add_dataset(seeded, "ds_b", frame(shift=0.5), role="monitoring_batch", model_id="mdl_t")
    await add_dataset(seeded, "ds_c", frame(missing=0.5), role="monitoring_batch", model_id="mdl_t")
    await add_dataset(seeded, "ds_other", frame(), role="monitoring_batch", model_id="mdl_other")

    summary = await process_pending()
    assert summary["models"] == ["mdl_t"]
    assert sorted((p["batch_id"], p["status"]) for p in summary["processed"]) == [("ds_a", "green"), ("ds_b", "red")]
    assert [r["batch_id"] for r in summary["rejected"]] == ["ds_c"]
    assert (await process_pending())["processed"] == []  # nothing left to do
    assert await repo.get_or_none(Collections.METRICS, metric_key("mdl_t", "ds_other"), MonitoringMetric) is None


async def test_registrar_saves_schedule_and_baseline(tmp_path: Path) -> None:
    repo = get_repo()
    await add_model(baseline=None)
    await add_dataset(tmp_path, "ds_dev", frame(), role="development")
    await add_dataset(tmp_path, "ds_oot", frame(), role="out_of_time")
    await repo.put(Collections.RUNS, "run_oot", Run(run_id="run_oot", model_id="mdl_t", dataset_id="ds_oot"))
    model = await repo.get(Collections.MODELS, "mdl_t", ModelRecord)
    ctx = StepContext(
        pipeline_id="pl_t",
        model=model,
        dataset_ids=["ds_dev", "ds_oot", "ds_unregistered"],
        artifacts={"run_ids": ["run_oot"]},
    )

    await MonitoringRegistrarImpl().register(ctx)

    schedule = await repo.get(Collections.SCHEDULES, "mdl_t", Schedule)
    assert schedule.cron == "0 6 * * 1" and schedule.enabled
    tags = (await repo.get(Collections.MODELS, "mdl_t", ModelRecord)).tags
    assert tags[TAG_BASELINE_DATASET] == "ds_oot" and tags[TAG_BASELINE_RUN] == "run_oot"

    await MonitoringRegistrarImpl().register(ctx, cron="0 * * * *")
    assert (await repo.get(Collections.SCHEDULES, "mdl_t", Schedule)).cron == "0 * * * *"


async def test_registrar_without_registered_dataset_only_saves_schedule() -> None:
    await add_model(baseline=None)
    model = await get_repo().get(Collections.MODELS, "mdl_t", ModelRecord)
    await MonitoringRegistrarImpl().register(StepContext(pipeline_id="pl_t", model=model, dataset_ids=["ds_dev"]))
    assert await get_repo().get(Collections.SCHEDULES, "mdl_t", Schedule)
    assert TAG_BASELINE_DATASET not in (await get_repo().get(Collections.MODELS, "mdl_t", ModelRecord)).tags
