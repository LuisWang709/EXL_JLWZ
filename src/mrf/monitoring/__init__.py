"""Run-time monitoring. Owner: A4.

Per-batch data quality (pandera schema from mrf.data.schemas, missing rate, ranges, row count),
PSI/CSI drift via mrf.validation (do not re-implement), alerts, scheduled reports
(Container Apps Job). Implements DataQualityChecker and MonitoringRegistrar.
"""
