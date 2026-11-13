# Python rebuild: usage and troubleshooting

## Current behavior

SAS/R-to-Python rebuilding is implemented. RebuildAgent creates candidates/feedback, run_parity compares records in a restricted subprocess, and ModelRunnerImpl scores with parity-proven code. The UI now provides standalone start, job status, failure reasons, code viewing/downloads. Standalone rebuilding does not replace H1/H2 or advance the original pipeline.

## If the UI has no result

1. The normal workflow reaches rebuilding only after H1 approval in Review queue; no result before that is expected.
2. Select the model in Models, open Python rebuild, click **Start Python rebuild** for a standalone job.
3. Empty fixture ID selects the uploaded/matching built-in package. An invalid explicit ID returns MRF-1404 without fallback.
4. **Refresh rebuild status** shows missing fixtures, policy violations, scoring crashes, or mismatches.
5. Success shows certificate/code download. Existing Python without references shows source and unassessed parity.
6. If cloud UI is old, deploy the matching API/UI images. Local edits do not replace cloud containers.

## Raw data is not a parity fixture

The locally supplied raw-data ZIP contains German Credit/Taiwan card data under data/raw. Directory placement does not register it with the API.
After preprocessing into data/clean, upload/register via /api/v1/datasets and associate dataset IDs with the pipeline. Raw German Credit without log_amount, age_band, default_flag is not M001 scoring input.

A complete package includes source, manifest.json, input_sample.csv, legacy_scores.csv, and usually coefficients.json for regression. Raw training data has neither fitted parameters nor original-system scores and cannot independently prove migration correctness. Built-in M001/M002/M004 fixtures are examples, not a universal compiler.

M003 is training code depending on give_me_some_credit.csv, without a portable trained model or score(input_csv) entry point. Those artifacts were not supplied, so it remains inventory/documentation only.

## Recorded verification

Machine-readable: docs/submission/rebuild-verification.json. Isolated local API, SQLite/mock LLM, scripted demo approvals.

| Model | Parity records | Mismatches | Development rows | Test rows |
| --- | --- | --- | --- | --- |
| M001 | 300 | 0 | 700 | 300 |
| M002 | 500 | 0 | 21000 | 9000 |
| M004 synthetic pricing | 300 | 0 | 700 | 300 |

All three produced code/certificates. M001 returning to awaiting_signoff after red drift is expected revalidation behavior. References are Python reproductions; real LLM translation and independent SAS/R execution need separate acceptance.

The supplied data dictionary still mentions an old SAS age-bin bug/Team B. Current M001 uses under-25 / 25-39 / 40-and-over bins and fixes chained comparisons. Fairness script/document labels were aligned from the previous under-30 / 30-44 / 45-and-over labels.
