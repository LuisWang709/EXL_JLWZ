# Architecture overview

The one-page submission diagram is derived from this maintainable source. Historical delivery dates below are planning context; use completion status for current acceptance.

## Components and data flow

```mermaid
flowchart LR
    subgraph Client
      UI[Streamlit UI A4]
      CLI[python -m mrf.run A1]
    end
    subgraph API["API container: FastAPI"]
      R["/api/v1 routes<br/>Envelope, codes, idempotency A1"]
      GD["Input guards A1<br/>PII 1004, injection 1005<br/>Archive/request limits 1002"]
      Q["Job executor A1<br/>asyncio queue and jobs table"]
      G["LangGraph A1<br/>States, retries, H1/H2<br/>Step timeouts 4001"]
      MCP["/mcp tool service<br/>A1 framework"]
    end
    subgraph Agents
      C[Classifier A1]
      D[Document writer A3]
      RT[Rater A3]
      RB[Rebuilder A2]
      RUN[Usability scoring A2]
      RP[Reports A3]
    end
    subgraph Tools["MCP tools"]
      T1[parse_code / get_inventory A1]
      T2[profile_data A2]
      T3[run_sandbox / run_parity A2]
      T4[search_kb A3]
      T5[compute_metrics A3]
    end
    LLM[(LLM client A1<br/>Azure OpenAI / alternatives)]
    KB[(Knowledge index A3)]
    DB[(Repository<br/>SQLite / Cosmos)]
    BLOB[(Blob / local files)]
    MLF[(Optional MLflow)]
    MON[Monitoring A4<br/>Quality, drift, alerts, reports]
    UI --> R
    CLI --> Q
    R --> GD --> Q --> G
    G --> C & D & RT & RB & RUN & RP
    C & D & RT & RB --> LLM
    C & D & RB & RUN & RP --> MCP
    MCP --> T1 & T2 & T3 & T4 & T5
    T4 --> KB
    G --> DB
    T1 & T2 & T3 --> BLOB
    RUN & RB --> MLF
    G -->|deployed| MON
    MON --> DB
    MON -->|Red model drift| G
```

Uploaded code, archive text, form fields, and review comments are screened before inclusion in LLM prompts. Errors identify file/type/line without echoing the matched value (`mrf.core.guards`; `config/pipeline.yaml: guards`).

## Azure deployment: swedencentral, Azure for Students

```mermaid
flowchart LR
    DEV[Developer] -->|PR| GH[GitHub Actions<br/>Ruff, mypy, pytest, Bandit, Redocly]
    GH -->|Successful main CI, cd-dev<br/>OIDC without stored secrets| ACR[(ACR: API / UI images)]
    subgraph SHARED[rg-mrf-a-shared]
      ACR
      AOAI[(Azure OpenAI<br/>gpt-5-mini)]
      COS[(Cosmos DB free tier<br/>mrf-dev / mrf-demo)]
    end
    subgraph ENV["rg-mrf-a-dev / rg-mrf-a-demo"]
      UIA[Streamlit :8501]
      APIA[FastAPI :8000<br/>Single replica]
      JOB[Hourly monitoring job]
      KV[(Key Vault: API key)]
      FS[(Azure Files /data<br/>Files, reports, tracking)]
      AI[(App Insights: logs / traces)]
    end
    USER[Reviewer / validator] -->|API-key sign-in| UIA -->|X-API-Key| APIA
    JOB -->|POST /monitoring/runs| APIA
    APIA -->|Managed identity| AOAI
    APIA -->|Managed identity, data-plane RBAC| COS
    APIA --> FS
    APIA -->|Managed identity| KV
    APIA --> AI
    ACR --> APIA & UIA
```

- Azure access uses user-assigned managed identity (`AZURE_CLIENT_ID`); no cloud keys in code/images. The application API key is in Key Vault.
- API is single-replica because jobs are in-process. Pipelines awaiting H1/H2 recover from stored state after restart.
- `/readyz` exposes runtime environment, storage backend, LLM provider/model, and guard state for external verification.

## Implementation snapshot: November 12

Real implementations are assembled explicitly. Local opt-in test doubles are separate from the deployment path.

| Module | Implementation | Owner |
| --- | --- | --- |
| Classification, orchestration, API, MCP framework, guards, evaluation | Implemented | A1 |
| Documentation, rating, analysis/validation reports, metrics | Implemented; real-provider prompt calibration remains acceptance work | A3 |
| Quality, monitoring registration, drift batches, monitoring reports, UI, Azure | Implemented | A4 |
| profile_data, run_sandbox, run_parity | Implemented | A2 |
| Rebuild agent, model runner, dataset/rebuild/run APIs, M001-M004 packages, parity certificates | Implemented by A1 for A2; A2 review remains required | A2 / A1 |

Rebuilding initially uses the LLM for `rebuild.llm_attempts` attempts; later, or if it produces no usable code, fitted parameter estimates are deterministically transcribed. Both paths require per-record sandbox parity before a certificate is issued. Deployment and independent-reference acceptance remain separate.

## Pipeline states

```mermaid
stateDiagram-v2
    [*] --> received
    received --> classified: Confidence >= 0.7
    received --> manual_review: MRF-2002
    classified --> doc_drafting
    doc_drafting --> doc_rating
    doc_rating --> doc_drafting: Failed, attempts < 3, feedback
    doc_rating --> manual_review: MRF-2101
    doc_rating --> awaiting_doc_approval: Score >= 80, no veto
    awaiting_doc_approval --> rebuilding: H1 approve
    awaiting_doc_approval --> doc_drafting: H1 reject
    rebuilding --> rebuilding: Parity failed, attempts < 5
    rebuilding --> manual_review: MRF-3002
    rebuilding --> parity_passed
    parity_passed --> usability_run
    usability_run --> awaiting_signoff: Reports ready
    awaiting_signoff --> deployed: H2 approve
    awaiting_signoff --> rebuilding: H2 reject
    deployed --> monitoring
    monitoring --> usability_run: PSI > 0.25 / Gini drop > 0.05
    manual_review --> classified: Human correction
    manual_review --> doc_drafting
    manual_review --> rebuilding
    manual_review --> failed
```

## Shared conventions

| Topic | Convention | Location |
| --- | --- | --- |
| Responses | Envelope; status success/accepted/error; errors/warnings always arrays | mrf.core.envelope |
| Codes | MRF-0000 through MRF-5000 | mrf.core.codes |
| States | 13 states and allowed transitions | mrf.core.states |
| Thresholds | Confidence 0.7; document 3 attempts; parity 5; pass 80; PSI 0.10/0.25 | config/pipeline.yaml |
| Interfaces | Classifier / DocWriter / Rater / Rebuilder / ModelRunner / ReportBuilder / DataQualityChecker / MonitoringRegistrar | mrf.contracts.agents |
| Numeric facts | Seven MCP tools; no LLM-invented numeric facts | mrf.mcp_server.tools |
| Retries | Orchestrator quality counters; client transient backoff 1s/2s/4s + jitter | A1 design |
