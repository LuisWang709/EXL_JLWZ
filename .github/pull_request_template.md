## What / Why

<!-- one or two sentences; link the board card -->

## Module & owner

- [ ] A1 orchestrator / api / llm / storage / mcp / classify
- [ ] A2 data / rebuild / parity / legacy models
- [ ] A3 rag / doc / rating / validation / reporting
- [ ] A4 ci-cd / infra / monitoring / ui

## Checklist

- [ ] CI green (ruff, mypy, pytest with mock LLM)
- [ ] Touches `openapi.yaml`, `src/mrf/contracts/*`, `src/mrf/core/*` or `config/pipeline.yaml`? → **A1 approval required**
- [ ] No secrets, no real data files committed
- [ ] Numbers in docs/reports come from tools / MLflow, not hand-typed
- [ ] Tests added / updated
