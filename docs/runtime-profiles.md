# Runtime profiles

Two default acceptance paths are maintained. Optional adapters remain available and are accepted separately; a demo does not need every adapter.

| Path | Configuration / dependencies | Files and jobs |
| --- | --- | --- |
| Local development/demo | `uv sync --extra data --extra ui --frozen`; `MRF_ENV=local`; SQLite; mock LLM | Local files, SQLite records/checkpoints, API background jobs; mock results are not real LLM KPIs |
| Azure dev/demo | Docker installs data/azure/mlops; Cosmos, managed identity, Azure OpenAI | Azure Files for files/checkpoints (SQLite DELETE journal); single API replica runs jobs; scheduled container calls API |

The frontend reads data and monitoring thresholds through REST only. Restart the API after policy changes. Save individual model schedules on the Monitoring page.

Optional features:

- `--extra mlops`: additional MLflow experiment logging; scoring works without it. Default SQLite, explicit tracking URI supported.
- `MRF_BLOB_ACCOUNT_URL`: Azure Blob adapter; permissions and container need separate acceptance. Local/Azure Files is the default.
- `--extra rag`: optional FAISS acceleration; otherwise local numpy retrieval. Azure AI Search is not implemented.
- `MRF_TOOL_TRANSPORT=http`: remote MCP debugging; default in-process, no separate tool deployment.
- `MRF_STUBS` / `Registry.stubs`: explicit local experiments/test doubles only; forbidden in cloud. Missing real implementations fail rather than silently falling back.

Adapter development/CI use `uv sync --all-extras --frozen`. Default profiles do not remove adapters or change REST/Protocol calls.

Scoring and monitoring share file snapshots within one operation, with no cross-operation file cache. Analysis/validation reports share fact collection, then render, check numbers, and save separately. H2 remains explicit.

Outstanding cloud, real LLM, and independent reference-score acceptance: [completion status](completion-status.md).
