# C04 Team A execution plan: Model Risk Factory

November 2, 2026, @Albert. Historical delivery plan; [completion status](completion-status.md) is the current implementation/acceptance record. Planned services, deadlines, and targets below are not completion claims.

## Confirmed scope and decisions

Four Team A members deliver identification -> documentation -> rating -> rebuild -> usability scoring -> registration/monitoring. Internal submission deadline: November 13 at 18:00. This replaces Team A's part of the earlier Team Plan & Schedule. Team B was canceled; the two-team distinction no longer applies.

| Topic | Decision | Reason |
| --- | --- | --- |
| Document retry | Quality failure immediately redrafts with feedback, maximum three attempts; API rate limits/timeouts use 1/2/4 seconds plus jitter | Waiting does not fix content; backoff addresses transient failures |
| Human gates | H1 document approval after rating; H2 validation sign-off before registration; other steps escalate on failure | Human oversight and accountable validation; Responsible AI is 15% of judging |
| Rebuild standard | Per-record parity against SAS/R reference results, with certificate | Challenge requires parity proof |
| Improvement claims | Measure workflow time, labor, cost, automation against a manual baseline, not changed predictive performance | Rebuild parity preserves model behavior |
| Monitoring | Per-batch quality, PSI, alerts, periodic report; red drift revalidation | Complete operational loop |

Minimum deliverables: 3-5 documented/inventoried models, one SAS/R Python rebuild/parity proof, automatic performance/stability/fairness report. Judging weights: business impact 30%, technical 25%, innovation 20%, Responsible AI 15%, presentation/Q&A 10%.

## End-to-end rules

Eleven workflow stages with H1/H2 as required human gates. Uncertain identification or exhausted rating/parity attempts enters the common manual-review queue; rejections return to the relevant work step unless the task is terminated.

- Rating: deterministic 60 (section coverage 20, evidence 20, variable consistency 20) plus separate LLM review 40 (method accuracy, limitations, clarity). Pass >=80 with no invented-variable/number veto. Feedback feeds the next draft.
- Separate retry counters: document three, parity five; transient LLM retries up to three at 1/2/4 seconds plus jitter. Exhausted transient calls count as a failed agent attempt.
- Shared KB plan: SS1/23 sources, document templates/examples, SAS/R/Python mapping notes. Current KB source limitations are in completion status.
- Shared MCP tools: parse_code, profile_data, get_inventory, search_kb, run_sandbox, run_parity, compute_metrics. Numeric facts come from tools.

## Ownership

| Member | Role | Scope | Deliverables |
| --- | --- | --- | --- |
| A1 Albert | Lead / agent architect | Graph/retries/gates, FastAPI/envelopes/jobs, classification, MCP framework, integration, submission | orchestrator/api/OpenAPI/architecture/README |
| A2 | Modeling/rebuild | Legacy code/exports/fixtures, data cleaning, Python rebuild/parity, certificates, scoring | legacy examples/fixtures/data/rebuild/certificates |
| A3 | Documentation/validation/RAI | KB, document agent, rules/LLM rating, metrics, reports, RAI | rag/doc/rating/validation/templates/RAI note |
| A4 | DevOps/monitoring/presentation | CI/CD, Bicep, telemetry/quality/drift, reports, UI, video/business case | workflows/infra/monitoring/UI/slides/video |

Implement PSI/CSI once in A3 validation; A4 calls them. A2 schemas are shared with quality checks. Reviews pair A1/A2 and A3/A4; A1 approves API changes. Contracts freeze November 3 to enable independent implementation.

## Milestones

| Milestone | Internal deadline | Exit criteria |
| --- | --- | --- |
| M0 environment | Nov 3 Tue 22:00 | Registration/repo/protection/CI/resources/LLM or fallback; OpenAPI v1 |
| M1 foundations | Nov 5 Thu 22:00 | Legacy models/fixtures/clean data, correct classification, searchable KB, dev CD |
| M2 MVP | Nov 7 Sat 16:00 | M001 identify -> document -> rate -> H1 -> rebuild -> parity via API |
| M3 freeze | Nov 10 Tue 22:00 | Azure full flow: scoring/report/H2/registration/alerts/periodic report |
| M4 pack | Nov 12 Thu 22:00 | Slides v1/video/RAI/architecture/README/rehearsal |
| M5 submit | Nov 13 Fri 18:00 | UCD email sent/archived; v1.0.0; demo frozen |
| M6 finale | Nov 22 Sun | Three 7+3-minute rehearsals, 25 Q&A, offline video |

Daily deliverables go on the board before the 21:00 stand-up; report blockers that evening. After feature freeze, only fixes, evaluation, and submission preparation.

## A1 daily plan

| Date | Task | Deliverable |
| --- | --- | --- |
| Nov 2 | UCD registration, repo/resource group, confirm Azure OpenAI/fallback, API v0 | Confirmation, v0, provider decision |
| Nov 3 | Freeze v1, skeleton, graph nodes, LLM backoff/usage/mock | CLI skeleton, CI |
| Nov 4 | SAS PROC/R glm-rpart/Python parsing, algorithm/purpose extraction, <.7 escalation | Four correct classifications, tests |
| Nov 5 | Pipeline/job/model/review routes, executor, SQLite/Cosmos abstraction, MCP | Working endpoints/Inspector |
| Nov 6 | <=3 doc/<=5 parity, H1/H2, audit | All state branches |
| Nov 7 | MVP integration by 16:00 | One-model identify through parity |
| Nov 8 | Scoring/validation/H2/monitoring registration | Local full flow |
| Nov 9 | Azure with A4, managed identity | Reachable demo |
| Nov 10 | Guards/codes/timeouts, freeze 22:00 | Uniform errors |
| Nov 11 | Five runs/model, duration/cost/attempts | Evaluation |
| Nov 12 | Architecture/README/AI declaration, rehearsal 19:00 | Draft pack |
| Nov 13 | Final checks/tag/email before 18:00 | Archived submission |
| Nov 14-22 | Keep demo available, rehearse, Q&A | Finale ready |

## A2 daily plan

| Date | Task | Deliverable |
| --- | --- | --- |
| Nov 2 | SAS OnDemand, German Credit/Give Me Some Credit/Taiwan data | Download script/license notes, no raw Git data |
| Nov 3-4 | M001 SAS PD, M002 R glm, M003 Python XGBoost, optional M004 SAS REG; parameters/scores/gold | Legacy packages and fixtures |
| Nov 5 | Missing/capping/encoding/splits, pandera, parity suite | Cleaned Parquet, handwritten reference parity |
| Nov 6 | Prompt/mapping, sandbox/parity MCP | M001 <=5 attempts |
| Nov 7 | MVP, usage/time/attempt tracking | MLflow record |
| Nov 8 | Score cleaned data, A3 metrics | Run JSON |
| Nov 9 | M002 rebuild, missing/reference-level edge cases | Two parity reports or gaps |
| Nov 10 | HTML/PDF certificate, freeze | Certificate |
| Nov 11 | Measure manual document/rebuild | Baseline timing |
| Nov 12 | Two rebuild/parity slides, sourced numbers | Slide content |
| Nov 13 | Deployment checks | Passing logs |

## A3 daily plan

| Date | Task | Deliverable |
| --- | --- | --- |
| Nov 2 | SS1/23, template, rubric | Template/rubric |
| Nov 3 | Source/template/mapping chunks/index; AI Search planned, FAISS fallback | Sourced search_kb |
| Nov 4 | RAG/tools document agent, evidence per claim | M001 document |
| Nov 5 | Rules/separate prompt review, deliberately bad calibration | Four ratings, bad samples fail |
| Nov 6 | AUC/Gini/KS/Brier/HL/PSI/CSI/fairness | Known-value tests |
| Nov 7 | MVP support | Integration |
| Nov 8-9 | Traffic-light analysis and process evidence, numeric checks | Reports, zero mismatches |
| Nov 10 | Freeze, age-band fairness | Analysis/mitigation |
| Nov 11 | One-page Responsible AI | RAI note |
| Nov 12-13 | Verify numbers/SS1/23 Q&A | Sign-off checklist |

## A4 daily plan

| Date | Task | Deliverable |
| --- | --- | --- |
| Nov 2 | Branch protection/PR template/owners/pre-commit, EUR20 budget alert | Rules |
| Nov 3 | Ruff/mypy/pytest/Bandit/Gitleaks/build, API/UI images | CI |
| Nov 4 | Bicep resources, GitHub OIDC | One-command dev |
| Nov 5 | main-dev/release-demo CD, smoke | Delivery |
| Nov 6 | Quality/drift/distribution/policy/Monitor alerts | Tests |
| Nov 7 | MVP, three drifted synthetic monthly batches | Demo data |
| Nov 8 | Scheduled HTML reports, App Insights workbook | First report |
| Nov 9 | Streamlit pipeline/review/report/monitoring, deploy with A1 | Azure UI |
| Nov 10 | Freeze tagged demo | Fixed environment |
| Nov 11 | Manual/agent time/cost, 250-model scenario | KPI slide, only after measurement |
| Nov 12 | <=3-minute video, <=10-slide deck | Links/PDF |
| Nov 13 | Final deck/upload | Final materials |

## API conventions and endpoints

External API is /api/v1 with uniform envelopes/codes. Long work is async 202 plus job_id. openapi.yaml is authoritative; frozen-contract changes require A1. MCP at /mcp uses Streamable HTTP for internal agent tools.

- Plural resource names, snake_case, ISO8601 UTC.
- Demo X-API-Key, production Entra ID direction; operator on review decisions.
- Idempotency-Key on async submissions, request_id in header/envelope/logs.
- Pagination page/page_size with data.pagination; breaking changes use /api/v2.

| Method | Path | Purpose / owner |
| --- | --- | --- |
| POST | /api/v1/pipelines | Upload/start full workflow, 202, A1 |
| GET | /api/v1/pipelines/{pipeline_id} | State/current step/attempts, A1 |
| GET | /api/v1/models, /models/{model_id} | Inventory/classification, A1 |
| POST | /api/v1/models/{model_id}/documents | Regenerate, 202, A3 |
| GET | /api/v1/models/{model_id}/documents/{doc_id} | Content/evidence, A3 |
| GET | /api/v1/models/{model_id}/documents/{doc_id}/ratings | Attempts/scores/comments, A3 |
| POST | /api/v1/models/{model_id}/rebuilds | Standalone rebuild, 202, A2 |
| GET | /api/v1/models/{model_id}/rebuilds/{rebuild_id} | Code/parity/certificate, A2 |
| POST | /api/v1/datasets | Register cleaned data, 201, A2 |
| GET | /api/v1/datasets/{dataset_id}/quality | Quality, A4 |
| POST | /api/v1/models/{model_id}/runs | Usability/batch scoring, 202, A2 |
| GET | /api/v1/models/{model_id}/runs/{run_id} | Metrics/output, A2 |
| GET | /api/v1/models/{model_id}/reports | analysis/validation/monitoring, A3/A4 |
| GET | /api/v1/reviews?status=pending | H1/H2/manual queue, A1 |
| POST | /api/v1/reviews/{review_id}/decision | approve/reject/edit, A1 |
| GET | /api/v1/monitoring/models/{model_id}/metrics | Per-batch drift/quality, A4 |
| GET | /api/v1/monitoring/alerts | Alerts, A4 |
| PUT | /api/v1/monitoring/schedules/{model_id} | UTC report cron, A4 |
| GET | /api/v1/jobs/{job_id} | Async state/result, A1 |
| GET | /healthz, /readyz | Liveness/readiness, A4 |

Pipeline states: received -> classified -> doc_drafting -> doc_rating -> awaiting_doc_approval (H1) -> rebuilding -> parity_passed -> usability_run -> awaiting_signoff (H2) -> deployed -> monitoring; manual_review and failed are side states.

Envelope: request_id, status success/accepted/error, code, message, data, errors[], warnings[]. Acceptance example: MRF-0202 with pipeline_id/job_id/poll.

| Code | HTTP | Meaning |
| --- | --- | --- |
| MRF-0000 | 200 | Success |
| MRF-0202 | 202 | Accepted job |
| MRF-1001-1006 | 413/415/422 | Input type/size/schema/PII/injection/body |
| MRF-1404 | 404 | Missing resource |
| MRF-2001 | 422 | Unparseable code |
| MRF-2002 | 422 | Identification <.7, manual review |
| MRF-2101 | 409 | Three document attempts exhausted |
| MRF-3001 | 409 | Parity failed |
| MRF-3002 | 409 | Five parity attempts exhausted |
| MRF-3003 | 422 | Sandbox policy violation |
| MRF-3101 | 422 | Data quality refused |
| MRF-3201 | 409 | Invalid state/action |
| MRF-4001/4002/4003 | 504/429/502 | LLM timeout/rate limit/invalid output |
| MRF-5000 | 500 | Unexpected failure |

## CI/CD and operational plan

Every PR passes CI before merging. Original plan: main deploys dev; release tags deploy demo; nightly real-provider evaluation. Current workflow details and acceptance are documented separately.

| Trigger | Workflow | Planned checks/actions |
| --- | --- | --- |
| PR | ci.yml | Ruff/mypy/mock pytest including parity/states, Bandit/Gitleaks/image build; blocks merge |
| main | cd-dev.yml | OIDC, ACR, apps, health smoke, mock flow; rollback on smoke failure |
| Release | cd-demo.yml | Independent demo environment; current implementation uses manual promotion |
| Nightly | nightly-eval.yml | One real-model flow, time/tokens evidence; alert rather than block |

Original resource plan: Container Apps API/UI/MCP; Jobs for scoring isolation/monitoring; Azure OpenAI with fallback; free AI Search; Azure ML/MLflow; Blob/Cosmos; Key Vault/identity; App Insights/Log Analytics. Several were simplified or remain optional/unimplemented: consult runtime profiles/completion status, not this plan, for actual architecture.

| Monitoring layer | Planned evidence | Planned action |
| --- | --- | --- |
| System | API latency/errors/restarts/LLM use/cost | 5xx >5% or daily cost >EUR3 -> email alert (not yet implemented) |
| Workflow | Step duration/retries/backoff/escalation spans | Manual queue >24h -> alert (reserved) |
| Data/model | Schema/missing/ranges/rows, PSI/CSI, score drift, labeled Gini | Bad structure rejects; .10-.25 amber; >.25 or Gini drop >.05 red/revalidate |

Periodic report plan: weekly production/hourly demo, counts/quality/drift/alerts/handling, stored artifact exposed through reports API/UI. Current hourly timer and per-model report cron are described in monitoring.md.

## Risks, collaboration, submission

| Risk | Response | Owner |
| --- | --- | --- |
| MVP delay | Cut M002, then M004, then use API docs instead of UI; keep monitoring/reports | A1 |
| Student Azure OpenAI unavailable | Check early; alternate region, pay-as-you-go with EUR20 budget, GitHub Models/OpenAI | A1 |
| LLM reviewer too lenient | Deterministic majority/vetoes, separate context, bad-document calibration | A3 |
| Invented document/report numbers | Tool facts and rendered-number verification | A3 |
| Coding/missing/reference-level differences | Per-record parity, mapping knowledge | A2 |
| SAS unavailable | Switch rebuild target to R M002 | A2 |
| Budget exhausted | Budget alerts, scale down dev, retain demo | A4 |
| Live demo failure | Backup video, fixed version, warm up before finale | A4 |

Daily 21:00 fifteen-minute stand-up; reviews within twelve hours; A1 approves contracts. Internal demos Nov 7 16:00/Nov 12 19:00, retrospective Nov 11. Presentation numbers require sourced evidence and A3 review.

Submission plan, internal cutoff Nov 13 18:00, UCD sender, official recipient Monika.Rawal@exlservice.com, subject `EXL Hackathon | <team name> | Challenge 04`. Recheck official competition notice before sending; this plan is not a sending instruction or receipt.

- [ ] <=10-slide solution: problem/method/architecture/results/RAI/next steps (A4).
- [ ] <=3-minute linked demo video (A4).
- [ ] Repository with README setup/OpenAPI (A1).
- [ ] One-page components/data/AI architecture (A1).
- [ ] One-page Responsible AI note (A3).
- [ ] AI tools/existing-code declaration (A1).
- [ ] Sent email and archive/receipt (A1).
