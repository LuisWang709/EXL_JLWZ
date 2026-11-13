# Completion status and external dependencies (2026-11-12)

This review uses the working tree and execution plan. Modeling definitions, independent legacy exports, and human sign-offs remain the responsible team members' decisions. Implementation and local verification do not establish deployed acceptance.

## Completed work

| Item | Result / evidence |
| --- | --- |
| Azure real LLM integration | User confirmed configuration; historical deployment records show managed-identity Azure OpenAI calls and M001 reaching monitoring. Local mock tests do not describe cloud runtime configuration |
| Lean default runtime | Local SQLite/files; cloud Cosmos/Azure Files. Blob, MLflow, remote MCP remain optional; see runtime profiles |
| Shared data/report facts | Per-operation file snapshots; score PSI calculated once; analysis/validation share facts but separately check numbers, store results, and retain sign-off |
| Explicit assembly | Registry directly references implementations. Missing modules fail; doubles require explicit local selection |
| Monitoring loop | Amber quality, missing evidence, and system failures no longer appear green. Red revalidation uses new data and preserves the baseline. Later red batches can be submitted on subsequent ticks after H2 completes |
| Alert handling | UI/API acknowledge and close with operator/time/resolution; legacy compatibility, pagination, full-history reporting |
| UI review | Background job refresh, duplicate-action prevention, saved configuration, batch uploads, evidence prompts, retained input on errors, persistent success messages, recoverable downloads |
| CI root causes | Docker context includes tests/fixtures; Ruff line length fixed; image fixture/real-module checks added |
| Rebuild UI | Standalone form, status refresh, failure messages, code downloads; UI/API regression coverage |
| Test data delivery | Original package preserved; two CSVs and field notes added under data/raw; matching binary hashes preserved; data excluded from Git/Docker |
| Three rebuilt models | M001/M002/M004 Python code, certificates, cleaned development/test scoring verified through an isolated API; see submission/rebuild-verification.json |
| Rebuild reference checks | Explicit rebuild must belong to the model and have passed parity; invalid explicit fixtures do not silently fall back |
| Azure Blob adapter | Managed-identity read/write/existence/snapshots implemented and connected to data readers; offline-double tests |
| Cloud stubs | Forced stubs forbidden in dev/demo; no implicit fallback; /readyz checks module assembly |
| Cron | API uses actual parser and rejects invalid ranges/zero steps before saving |
| MLflow | Honors explicit MLFLOW_TRACKING_URI, defaults SQLite; deprecated forced file-store configuration removed |
| Evaluation | Strict exit status, mock rejection, full-data-scoring markers, HTTP checks, separate output; skipped scoring is not full acceptance |
| Nightly evaluation | nightly-eval.yml checks real provider, runs single-model evaluation, uploads evidence; variables/manual first run required before scheduling |
| Documentation | Old stub/profiling statements corrected; official SS1/23 version index, 25 Q&A entries, age-band labels aligned |
| Submission material | Ten-page review PDF, one-page architecture/RAI, content, narration, video storyboard, manual-baseline template, email draft |

## Acceptance work and owner decisions still required

| Item | Missing condition / next action |
| --- | --- |
| Latest real LLM end-to-end results | Azure is configured; rerun current code in dev and save evidence. This session lacks a usable dev API endpoint/credential; mock cannot substitute. Cloud managed identity requires no local model key |
| Latest cloud regression/demo freeze | Verify API/UI, Cosmos/identity, files, timers on current version before release tagging. Previous local checks/CI/image build passed, latest cloud version was not rechecked |
| Budget/operations | Confirm currency, recipients, thresholds, notification channels. App Insights is wired; Azure Monitor alert rules/workbooks remain unimplemented/unaccepted |
| M003 scoring | Supplied data covers German Credit/Taiwan cards; Give Me Some Credit, trained artifact, reference scores missing. Existing Python is training code; documentation only |
| Independent SAS/R parity acceptance | Demo references are Python reproductions. Obtain original-system parameter/score exports and confirm provenance; do not overwrite fixtures to imply independence |
| Manual baseline/benefits | Real human timing and A1-approved configuration required; no measured savings/ROI claimed |
| Data/fairness/regulatory sign-off | A2 verifies sources/licenses/fields/target/legacy behavior; A3 decides mitigation, thresholds, Responsible AI; automated scripts do not make these decisions |
| Official SS1/23 full text | Current official index and PDF link checked; redistribution terms and detailed interpretation require A3. KB currently holds team summaries |
| Editable PPTX | At the recorded handoff, the presentation skill runtime was unavailable; static PDF and source content were delivered. A later local PPTX must be assessed separately |
| Video/publication | Storyboard exists; record final environment, review sensitive information, provide accessible upload URL |
| Member statements/email/release | Members confirm AI-use scope; lead fills final links/recipient, sends and archives. Drafts are not proof of sending/review |

## Optional extensions with usable alternatives

- Azure AI Search is not implemented; local TF-IDF with numpy/optional FAISS provides knowledge retrieval.
- RDS/RData and SQL readers remain unconnected; supplied CSV/XLS paths work.
- Strong multi-tenant isolation, external queues, multiple API replicas remain production work; current demo uses single-replica/API-key access.

## Verification

Recorded completion checks: Ruff, mypy, Bandit medium/high checks, pytest **314 passed**, OpenAPI lint without errors. A later local review on November 13 ran the expanded suite: **324 passed**, with mock LLM and isolated storage. These counts describe different test revisions, not real-provider acceptance.
Regression coverage includes standalone rebuilds, triggering-batch revalidation to H2, baseline retention, legacy alerts/pagination, configuration display, UI actions.
An isolated SQLite/mock demo processed M001 and four monitoring batches through real API modules; browser checks covered acknowledge/close, success messages, background refresh.

```bash
uv sync --all-extras --frozen
uv run ruff check .
uv run mypy
uv run pytest -q
uv run bandit -c pyproject.toml -r src -ll --skip B608
docker build -f docker/Dockerfile.api -t mrf-api:verify .
```

On restricted Windows, set TEMP/TMP and pytest --basetemp under workspace .tmp. Historical results: .tmp/project-completion/junit-streamline.xml. Data/runtime databases are not committed.

For deployed acceptance, set MRF_EVAL_API_KEY and run:

```bash
uv run python scripts/evaluate.py --api <dev> --model M001 --dataset <development-id> --dataset <test-id> --runs 5 --strict --require-real-llm --report-out var/eval/evaluation.md
```

External references: [SS1/23 official index](https://www.bankofengland.co.uk/prudential-regulation/publication/2023/may/model-risk-management-principles-for-banks-ss), [Azure Blob SDK](https://learn.microsoft.com/en-us/python/api/azure-storage-blob/azure.storage.blob.containerclient?view=azure-python).
