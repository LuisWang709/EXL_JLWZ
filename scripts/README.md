# scripts

- `get_data.py` (A2) – download public datasets into `data/raw/` and print licence notes
- `seed_demo.py` (A1) – register legacy models + datasets through the API for the demo
- `evaluate.py` (A1) – run every model N times end to end; process KPIs (time, attempts, tokens, cost) -> `docs/evaluation.md`
- `make_drift_batches.py` (A4) – synthetic monthly batches with drift

`evaluate.py --strict` exits nonzero for a failed/escalated pipeline, misclassification or stub.
`--require-real-llm` rejects mock/unknown providers before executing; `--out-dir` selects the raw evidence directory.
The report labels evaluations without successful dataset scoring as incomplete, even with a real LLM.
Local evaluation creates a fresh in-memory repository per run; existing dataset IDs are therefore intended for
`--api` mode (register them on that API first).

`build_submission.py` exports the review presentation, one-page architecture and RAI note as PDFs from the
versioned submission sources. Its PDF dependencies are optional and do not change application dependencies.
