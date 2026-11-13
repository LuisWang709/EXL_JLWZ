# Monitoring and alerts

`monitoring` means the model passed H2 and was registered for ongoing checks. It does not automatically train models or repeat the entire pipeline indefinitely.
New batches pass quality checks, then are scored with parity-proven Python code. Score PSI, feature CSI, and labeled Gini change are compared with the healthy baseline.

## Triggers

Defaults: `config/pipeline.yaml`. The UI reads actual thresholds from `GET /api/v1/monitoring/schedules/{model_id}`.

| Condition | Result |
| --- | --- |
| Zero rows, missing declared columns, schema failure, missing rate above red threshold | Red data_quality alert; refuse scoring; no model revalidation |
| Rows below min_rows or missing rate above amber threshold | Amber data_quality alert; continue scoring; batch at least amber |
| PSI/CSI >= 0.10 and <= 0.25 | Amber drift alert |
| PSI/CSI > 0.25 or Gini drop > 0.05 | Red drift alert; attempt triggering-batch usability run -> validation report -> H2 |
| No comparable drift/performance evidence | Amber, explicitly unassessed rather than green |
| Missing baseline, scoring error, other system failure | Red system alert; job failure reason retained |

Stable IDs for model/batch/alert kind prevent duplicate alerts. Recorded batches are not scored twice.
The current single-replica API serializes work per model in-process; multiple replicas need a shared queue/distributed locks.

## Revalidation and baseline

Red-drift revalidation uses the triggering dataset, recorded on H2, the report summary, and new Run. It does not merely rerun development data.
If an investigation/H2 is active, later red alerts remain pending; later monitoring ticks submit them after the earlier investigation finishes.
Closing an unsubmitted alert records human handling and prevents its automatic resubmission.
H2 approval keeps the original healthy baseline. Changing the baseline requires separate data/model-change review.

## UI actions

1. Select the model; inspect baseline and enabled state. Upload cleaned monitoring_batch data, not raw training tables.
2. **Process new batches** starts a background job. The page refreshes; leaving does not cancel the job.
3. Filter Alerts by open/acknowledged/closed, page through them, inspect evidence.
4. Acknowledge records owner/time; Close requires a resolution and records who/when. Repeats preserve original handling.
5. Cron uses UTC for periodic reports. An hourly cloud timer checks new batches. Pausing stops automatic processing. With an enabled schedule, the report button processes pending batches before reporting.

Acknowledging/closing does not change metrics, erase red batches, or replace H2. Reports distinguish unresolved/unacknowledged alerts, show handling, and count full history.
Channels are in-app alerts, reports, logs; email/Teams/Slack are not implemented. `queue_sla` is reserved with no automatic trigger.

Acknowledge/close API calls require `X-Operator`. New fields are additive; legacy `acknowledged` remains supported.
