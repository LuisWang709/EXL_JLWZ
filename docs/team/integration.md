# Module integration guide

For A2/A3/A4. Implement your Protocol class and register it at the explicit assembly point; the orchestrator handles persistence and workflow routing.

## 0. Run locally

```bash
uv sync --extra data --extra ui --frozen
uv run pytest
uv run python -m mrf.run --model M001 --auto-approve
uv run uvicorn mrf.api.app:app --reload
```

Tests use mock LLM. The CLI uses real modules but skips usability scoring without datasets. API docs: localhost:8000/docs; MCP: /mcp/.

## 1. Implement a Protocol and wire it explicitly

`mrf.orchestrator.registry._implementations` directly references the classes below, using no-argument constructors. Change that assembly point to replace an implementation. Missing implementations fail in every environment. Only local opt-in MRF_STUBS is supported; dev/demo forbid it and /readyz checks assembly.

| Slot | module:Class | Owner |
| --- | --- | --- |
| classifier | mrf.agents.classify.agent:ClassifierAgent | A1 |
| doc_writer | mrf.agents.doc.agent:DocAgent | A3 |
| rater | mrf.rating.rater:DocRater | A3 |
| rebuilder | mrf.agents.rebuild.agent:RebuildAgent | A2 |
| runner | mrf.agents.rebuild.runner:ModelRunnerImpl | A2 |
| report_builder | mrf.reporting.builder:ReportBuilderImpl | A3 |
| quality_checker | mrf.monitoring.quality:QualityCheckerImpl | A4 |
| monitoring | mrf.monitoring.registrar:MonitoringRegistrarImpl | A4 |

```python
from mrf.contracts.agents import StepContext
from mrf.contracts.models import Document, Rating
from mrf.core.ids import new_id

class DocRater:
    async def rate(self, ctx: StepContext, document: Document) -> Rating:
        ...
        # Return a complete Rating including ID, attempt, scores, comments, and usage.
```

- One call is one attempt. Do not add internal quality-retry loops. ctx.feedback contains the previous rating, parity diagnosis, or human comments; orchestration owns counting.
- Raise MRFError. Codes 3001/4001/4002/4003 count as failed attempts and follow retry rules; other MRF codes escalate. Unexpected exceptions fail the pipeline.
- Orchestration saves returned objects. Save only additional artifacts your implementation owns.
- Explicit local MRF_STUBS=rater or all can select doubles while developing.
- CLI prints the actual agents mapping at startup.

## 2. Use the shared LLM client

```python
from mrf.llm import ChatMessage, get_llm
res = await get_llm().chat(
    [ChatMessage(role="system", content=SYSTEM), ChatMessage(role="user", content=prompt)],
    role="rater",  # Model mapping and mock-response key.
    json_schema=ReviewOutput,  # Optional Pydantic schema; validated res.parsed.
)
```

One JSON repair is attempted before MRF-4003. Transient errors use 1/2/4 seconds plus jitter, then 4002/4001. Do not add another retry layer. Usage/time/cost accrue to Pipeline.usage.

```python
from mrf.llm import get_mock
mock = get_mock()
mock.register("rater", {"score": 34, "comments": []})
mock.register("doc_writer", [bad_draft, good_draft])
mock.register("rebuilder", lambda messages, schema: {...})
mock.fail_next("rater", "rate_limit", times=2)
mock.calls  # Inspect actual prompts.

from mrf.llm.mock import MockLLM
MockLLM.register_default("rater", lambda messages, schema: {...})
# Register at module import; explicit test responders take precedence.
```

Default offline responders let real agent modules run without provider keys in CI.

## 3. MCP tools

```python
from mrf.mcp_server.client import get_tools
tools = get_tools()  # Fresh per step, with call records.
chunks = await tools.call("search_kb", query="model limitations", top_k=5)
llm_tools = await tools.as_openai_tools(["parse_code", "profile_data"])
evidence = tools.records[0].evidence()
```

Implement typed async functions in tools/<area>.py, retain signatures/docstrings, and add them to ALL_TOOLS. Docstrings are the LLM-visible description. Raise MRFError; codes survive the MCP boundary.
Use InProcessGateway(overrides={"profile_data": fake_profile}) in tests.
For Inspector: npx @modelcontextprotocol/inspector, Streamable HTTP, http://localhost:8000/mcp/.

## 4. Storage

```python
from mrf.storage import Collections, get_blobs, get_repo
repo = get_repo()
await repo.put(Collections.DATASETS, ds.dataset_id, ds)
ds = await repo.get(Collections.DATASETS, dataset_id, Dataset)  # Missing -> MRF-1404.
page = await repo.find(Collections.RATINGS, Rating, where={"doc_id": doc_id}, order_by="attempt")
page = await repo.find(Collections.ALERTS, Alert, where={"severity": ["amber", "red"], "model_id": mid})
ref = await get_blobs().put_bytes(f"rebuilds/{rb_id}/model.py", code.encode(), media_type="text/x-python")
path = get_blobs().local_path(ref.uri)
```

Filters support equality, dotted fields, and lists as IN. Discuss more complex queries with A1. Use if_version for optimistic concurrent writes; conflict is MRF-3201.

## 5. Add an asynchronous endpoint

```python
from mrf.api.deps import IdemKey, accepted_response
from mrf.contracts.models import Job
from mrf.jobs import get_executor, register_handler

@register_handler("rebuild")
async def run_rebuild(job: Job) -> dict:
    ...
    return {"rebuild_id": rb.rebuild_id}

@router.post("/{model_id}/rebuilds", status_code=202)
async def create_rebuild(model_id: str, body: RebuildCreate, request: Request, idem: IdemKey = None):
    job, _ = await get_executor().submit("rebuild", {"model_id": model_id},
        payload=body.model_dump(mode="json"), idempotency_key=idem)
    return accepted_response(request, job)
```

The client polls GET /api/v1/jobs/{id}. Handler return values go to Job.result; MRFError goes to Job.error. Work is serialized per model/pipeline. Import the handler module at startup, commonly through its router. Authentication, request IDs, and errors are global; routes use ok/accepted_response or raise MRFError.

## 6. Monitoring-triggered revalidation

```python
from mrf.orchestrator.service import trigger_revalidation
job = await trigger_revalidation(model_id, reason="PSI 0.31 on income", dataset_id=triggering_batch_id)
```

Pass the triggering batch ID for monitoring investigations. Invalid state/duplicate active investigation raises MRF-3201. The flow returns to usability_run, generates reports, and awaits H2; baseline preservation is described in the monitoring guide.
