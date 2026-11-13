# Contributing

## Branches

| Branch | Purpose |
| --- | --- |
| `main` | Protected; changes arrive through PRs. Merges trigger dev deployment once CD is enabled |
| `feat/a1-*` `feat/a2-*` `feat/a3-*` `feat/a4-*` | Individual feature branches from `main`; make small commits and open PRs early |
| `fix/*` | Bug fixes |
| Tags `v*` | Demo releases; `v1.0.0` is the planned submission version |

```bash
git switch main
git pull
git switch -c feat/a2-parity-suite
# Make and commit changes.
git push -u origin feat/a2-parity-suite
# Open a pull request.
```

## Commit messages

Use `<type>(<scope>): <summary>`. Types: feat, fix, docs, test, refactor, chore, ci. Use the module as scope, for example `feat(orchestrator): add parity retry loop`.

## Pull requests and review

- CI must pass: Ruff, mypy, pytest with mock LLM.
- Review pairs: A1/A2 and A3/A4; target a response within 12 hours.
- Changes to `openapi.yaml`, `src/mrf/contracts/`, `src/mrf/core/`, or `config/pipeline.yaml` require A1 approval. Only add optional fields; field removal/renaming requires `/api/v2`.
- Before the daily 21:00 stand-up, link deliverables or PRs on the project board.

## Code conventions

- Integrate modules through `mrf.contracts.agents` Protocols and MCP tools, not another module's internal implementation.
- Raise `MRFError(MRFCode.X, ...)` on failure; do not return `None` or unstructured exceptions.
- Read thresholds from `mrf.config.get_policy()` rather than hard-coding them.
- Agents obtain numeric facts from tools or MLflow; LLMs must not invent them.
- The orchestrator owns quality-retry counters. Transient LLM retries are handled in `mrf.llm`.
- Never commit real data, secrets, or `.env`. Fixtures belong in `tests/fixtures/`, each smaller than 1 MB.
- Tests use mock LLM by default; mark real-provider tests `@pytest.mark.llm`. CI excludes them.
