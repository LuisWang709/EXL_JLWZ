"""Run-time monitoring. Owner: A4.

Per-batch data quality (pandera schema from mrf.data.schemas, missing rate, row count), PSI/CSI drift via
mrf.validation (never re-implemented here), alerts, and re-validation on red drift.

Slots picked up by the orchestrator registry (no-arg constructors):
    quality_checker  mrf.monitoring.quality:QualityCheckerImpl
    monitoring       mrf.monitoring.registrar:MonitoringRegistrarImpl

Job handlers (registered when mrf.api.routers.monitoring is imported):
    monitoring_batch  one batch: quality -> score -> drift -> metric -> alerts -> trigger_revalidation on red
    monitoring_tick   every pending batch of every enabled schedule (called by the Container Apps Job)

Thresholds: config/pipeline.yaml ``monitoring`` (psi_amber, psi_red, gini_drop_red, min_rows, missing_rate_*).
"""
