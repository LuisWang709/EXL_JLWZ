# 接入指南：如何把你的模块接进流水线

适用于 A2 / A3 / A4。下面所有内容都已在 `main` 上实现并有测试覆盖。你只需要写自己的类，不用改编排器。

## 0. 先跑起来

```bash
uv sync
uv run pytest                                          # 使用 mock LLM，不需要网络
uv run python -m mrf.run --model M001 --auto-approve   # 真实模块；未提供数据集时不执行可用性评分
uv run uvicorn mrf.api.app:app --reload                # http://localhost:8000/docs，MCP 在 /mcp/
```

## 1. 实现你的 Protocol（约定路径即可自动接入）

编排器启动时会按下表的路径 import 你的类，**用无参构造函数**实例化。仅本地环境在模块不存在时允许 stub；
dev/demo 缺少任何实现或设置 `MRF_STUBS` 都会报错，`/readyz` 检查模块能否加载。

| 槽位 | 路径 `module:Class` | 负责人 |
| --- | --- | --- |
| classifier | `mrf.agents.classify.agent:ClassifierAgent` | A1 |
| doc_writer | `mrf.agents.doc.agent:DocAgent` | A3 |
| rater | `mrf.rating.rater:DocRater` | A3 |
| rebuilder | `mrf.agents.rebuild.agent:RebuildAgent` | A2 |
| runner | `mrf.agents.rebuild.runner:ModelRunnerImpl` | A2 |
| report_builder | `mrf.reporting.builder:ReportBuilderImpl` | A3 |
| quality_checker | `mrf.monitoring.quality:QualityCheckerImpl` | A4 |
| monitoring | `mrf.monitoring.registrar:MonitoringRegistrarImpl` | A4 |

```python
# src/mrf/rating/rater.py   (A3 示例)
from mrf.contracts.agents import StepContext
from mrf.contracts.models import Document, Rating
from mrf.core.ids import new_id


class DocRater:
    async def rate(self, ctx: StepContext, document: Document) -> Rating:
        ...
        return Rating(rating_id=new_id("rating"), doc_id=document.doc_id, attempt=ctx.attempt, ...)
```

规则：

- **一次调用 = 一次尝试**，不要在里面自己循环重试。编排器会把上次的意见放进 `ctx.feedback`（评级 comments、parity 差异、人工驳回意见），并负责计数。
- 失败时抛 `MRFError(MRFCode.X, "...")`：
  - 3001 / 4001 / 4002 / 4003 记为一次失败尝试，照常走重试规则；
  - 其他 MRF 码直接转人工审核；
  - 非 MRF 的异常会让流水线进入 `failed`。
- 返回的对象由编排器负责保存到 Repository，你**不需要**自己写库（自己额外存的东西除外）。
- 半成品不想被自动接入时，可以设置 `MRF_STUBS=rater` 或 `MRF_STUBS=all` 强制用 stub。
- 查看当前实际用的是哪个实现：运行 `python -m mrf.run` 时首行会打印 `agents={...}`。

## 2. 调用 LLM

```python
from mrf.llm import ChatMessage, get_llm

res = await get_llm().chat(
    [ChatMessage(role="system", content=SYSTEM), ChatMessage(role="user", content=prompt)],
    role="rater",                   # 用于选模型（config llm.role_models / MRF_LLM_REVIEWER_MODEL），也是 mock 的键
    json_schema=ReviewOutput,       # 可选：Pydantic 类 → res.parsed 已校验；不合法时自动修复 1 次，仍失败抛 MRF-4003
)
```

- 限流和超时由封装层按 1s / 2s / 4s + 抖动 重试 3 次，用尽后抛 4002 / 4001。**不要再自己包一层重试。**
- token、费用、耗时会自动累计到 `Pipeline.usage`，作为流程提升 KPI 的数据来源。

测试中使用 mock：

```python
from mrf.llm import get_mock

mock = get_mock()
mock.register("rater", {"score": 34, "comments": []})        # 固定返回
mock.register("doc_writer", [bad_draft, good_draft])         # 按调用次序返回
mock.register("rebuilder", lambda messages, schema: {...})   # 根据提示词动态生成
mock.fail_next("rater", "rate_limit", times=2)               # 注入故障
mock.calls                                                   # 断言实际发给 LLM 的内容
```

给你的 role 配一个离线默认响应，CI 和没有 key 的演示就能直接跑你的真实智能体（参考 `mrf/agents/classify/agent.py` 末尾）：

```python
from mrf.llm.mock import MockLLM

MockLLM.register_default("rater", lambda messages, schema: {...})   # 模块被 import 时注册；测试里 register() 的优先级更高
```

## 3. 调用 / 实现 MCP 工具

```python
from mrf.mcp_server.client import get_tools

tools = get_tools()                                    # 每次步骤新建一个，自带调用记录
chunks = await tools.call("search_kb", query="model limitations", top_k=5)
llm_tools = await tools.as_openai_tools(["parse_code", "profile_data"])  # 给 LLM function calling 用
evidence = tools.records[0].evidence()                 # Evidence(source="tool", ref="tool:search_kb#call_1")
```

- **实现工具**：直接在 `src/mrf/mcp_server/tools/<你的文件>.py` 中替换 `NotImplementedError`，签名和 docstring 保持不变（docstring 就是 LLM 看到的工具描述）。工具会自动注册到 `/mcp`，失败时抛 `MRFError`，返回码会原样传给调用方。
- **测试时替换工具**：`InProcessGateway(overrides={"profile_data": fake_profile})`。
- **用 MCP Inspector 调试**：`npx @modelcontextprotocol/inspector`，选择 Streamable HTTP，地址填 `http://localhost:8000/mcp/`。

## 4. 存储

```python
from mrf.storage import Collections, get_blobs, get_repo

repo = get_repo()
await repo.put(Collections.DATASETS, ds.dataset_id, ds)
ds = await repo.get(Collections.DATASETS, dataset_id, Dataset)          # 不存在 → MRF-1404
page = await repo.find(Collections.RATINGS, Rating, where={"doc_id": doc_id}, order_by="attempt")
page = await repo.find(Collections.ALERTS, Alert, where={"severity": ["amber", "red"], "model_id": mid})
ref = await get_blobs().put_bytes(f"rebuilds/{rb_id}/model.py", code.encode(), media_type="text/x-python")
path = get_blobs().local_path(ref.uri)                                  # 需要文件路径时（pandas / pyreadstat）
```

- `where` 只支持等值匹配（可以用点号访问嵌套字段，值为列表时表示 IN）。需要更复杂的查询请先告诉 A1。
- 并发写同一个文档时用 `if_version=` 做乐观锁，冲突会抛 MRF-3201。

## 5. 新增一个 202 端点

```python
# src/mrf/api/routers/rebuilds.py   (A2 示例)
from fastapi import Request
from mrf.api.deps import IdemKey, accepted_response, ok
from mrf.contracts.models import Job
from mrf.jobs import get_executor, register_handler


@register_handler("rebuild")                       # 模块被 import 时注册
async def run_rebuild(job: Job) -> dict:
    ...                                            # 返回值写入 Job.result；抛 MRFError 则写入 Job.error
    return {"rebuild_id": rb.rebuild_id}


@router.post("/{model_id}/rebuilds", status_code=202)
async def create_rebuild(model_id: str, body: RebuildCreate, request: Request, idem: IdemKey = None):
    job, _ = await get_executor().submit("rebuild", {"model_id": model_id},
                                         payload=body.model_dump(mode="json"), idempotency_key=idem)
    return accepted_response(request, job)         # 202 + {job_id, poll}，客户端轮询 GET /api/v1/jobs/{id}
```

- 同一个 `model_id` 或 `pipeline_id` 的任务会串行执行。
- 自定义 handler 所在的模块需要被 import 到。最简单的做法是在对应的 router 文件里定义它（router 在应用启动时就会 import）。
- 鉴权（`X-API-Key`）、`request_id`、错误信封都已全局处理，路由里只需要 `return ok(request, data)` 或 `raise MRFError(...)`。

## 6. A4：触发重新验证

```python
from mrf.orchestrator.service import trigger_revalidation

job = await trigger_revalidation(model_id, reason="PSI 0.31 on income")   # 流水线不在 monitoring 状态时抛 MRF-3201
```

调用后流水线回到 `usability_run`，之后照常重新生成报告并等待 H2。
