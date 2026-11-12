# 架构总览

> 1 页架构图（提交用 PNG/PDF）由 A1 在 11/12 根据本文导出；本文是可维护的源文件。

## 组件与数据流

```mermaid
flowchart LR
    subgraph Client
      UI[Streamlit UI<br/>A4]
      CLI[python -m mrf.run<br/>A1]
    end

    subgraph API["API 容器 (FastAPI)"]
      R["/api/v1 路由<br/>信封·返回码·幂等<br/>A1"]
      GD["输入防护<br/>个人数据 MRF-1004·提示词注入 MRF-1005<br/>压缩包/请求体上限 MRF-1002<br/>A1"]
      Q["任务执行器<br/>asyncio 队列 + jobs 表<br/>A1"]
      G["LangGraph 编排器<br/>状态机·重试·H1/H2<br/>每步超时 MRF-4001<br/>A1"]
      MCP["/mcp 工具服务<br/>FastMCP<br/>A1 框架"]
    end

    subgraph Agents
      C[识别智能体 A1]
      D[说明书智能体 A3]
      RT[评级器 A3]
      RB[重建智能体 A2]
      RUN[可用性运行 A2]
      RP[报告生成 A3]
    end

    subgraph Tools["MCP 工具"]
      T1[parse_code / get_inventory A1]
      T2[profile_data A2]
      T3[run_sandbox / run_parity A2]
      T4[search_kb A3]
      T5[compute_metrics A3]
    end

    LLM[(LLM 封装 A1<br/>Azure OpenAI / 备选)]
    KB[(RAG 索引 A3)]
    DB[(Repository<br/>SQLite / Cosmos)]
    BLOB[(Blob / 本地文件)]
    MLF[(MLflow)]
    MON[监控任务 A4<br/>质量·PSI·告警·定期报告]

    UI --> R
    CLI --> Q
    R --> GD --> Q --> G
    G --> C & D & RT & RB & RUN & RP
    C & D & RT & RB --> LLM
    C & D & RB & RUN & RP -->|MCP| MCP
    MCP --> T1 & T2 & T3 & T4 & T5
    T4 --> KB
    G --> DB
    T1 & T2 & T3 --> BLOB
    RUN & RB --> MLF
    G -->|deployed| MON
    MON --> DB
    MON -->|PSI 超阈值| G
```

上传的代码、压缩包内的文本文件、表单字段和审核意见，都要先经过输入防护，才会进入任何 LLM 提示词。报错只给出文件名、类型和行号，不回显匹配到的内容（`mrf.core.guards`，规则在 `config/pipeline.yaml: guards`）。

## Azure 部署（swedencentral，Azure for Students）

```mermaid
flowchart LR
    DEV[开发者] -->|PR| GH[GitHub Actions<br/>ci: ruff·mypy·pytest·bandit·redocly]
    GH -->|main 变绿 → cd-dev<br/>OIDC 登录，无密钥| ACR[(ACR<br/>mrf-api / mrf-ui 镜像)]

    subgraph SHARED[rg-mrf-a-shared]
      ACR
      AOAI[(Azure OpenAI<br/>gpt-5-mini)]
      COS[(Cosmos DB 免费层<br/>mrf-dev / mrf-demo)]
    end

    subgraph ENV["rg-mrf-a-dev / rg-mrf-a-demo"]
      UIA[mrf-ui<br/>Streamlit :8501]
      APIA["mrf-api<br/>FastAPI :8000，单副本"]
      JOB[mrf-monitor<br/>定时任务（每小时）]
      KV[(Key Vault<br/>API key)]
      FS[(Azure Files /data<br/>blob·报告·mlruns)]
      AI[(App Insights<br/>日志·trace)]
    end

    USER[评审 / 验证人员] -->|API key 登录| UIA -->|X-API-Key| APIA
    JOB -->|POST /monitoring/runs| APIA
    APIA -->|托管身份| AOAI
    APIA -->|托管身份·数据面 RBAC| COS
    APIA --> FS
    APIA -->|托管身份| KV
    APIA --> AI
    ACR --> APIA & UIA
```

- 所有 Azure 访问都走用户分配的托管身份（`AZURE_CLIENT_ID`），代码和镜像里没有云密钥。只有 API key 存在 Key Vault 里。
- `mrf-api` 固定单副本，因为任务队列在进程内。容器重启后，停在 H1/H2 的流水线会从存储的状态恢复。
- `GET /readyz` 返回 `runtime`（环境、存储后端、LLM 提供方和模型、防护开关），不重新登录也能从外部核对部署配置。

## 实现状态（11/12）

所有智能体和工具都是真实实现，流水线里不再有 stub。

| 模块 | 实现 | 负责人 |
| --- | --- | --- |
| 识别、编排、API、MCP 框架、输入防护、评估脚本 | 真实 | A1 |
| 说明书、评级、分析/验证报告、指标 | 真实，提示词待真实 LLM 校准 | A3 |
| 数据质量、监控注册、漂移批处理、监控报告、UI、Azure | 真实 | A4 |
| `profile_data`、`run_sandbox`、`run_parity` | 真实 | A2 |
| 重建智能体、可用性运行、数据集 / 重建 / 运行接口、遗留模型包 M001–M004、一致性证书 | 真实（A1 代 A2 完成，待 A2 审阅） | A2 / A1 |

重建分两条路径：前 `rebuild.llm_attempts` 次由 LLM 翻译遗留代码；之后或 LLM 不可用时，按遗留系统导出的参数估计值确定性转写。两条路径产出的代码都要在沙箱里通过逐笔一致性测试，才会签发一致性证书。

## 流水线状态机

```mermaid
stateDiagram-v2
    [*] --> received
    received --> classified: 识别 (置信度 ≥ 0.7)
    received --> manual_review: MRF-2002
    classified --> doc_drafting
    doc_drafting --> doc_rating
    doc_rating --> doc_drafting: 不通过 且 尝试 < 3（评审意见回灌）
    doc_rating --> manual_review: MRF-2101
    doc_rating --> awaiting_doc_approval: ≥ 80 且无否决
    awaiting_doc_approval --> rebuilding: H1 批准
    awaiting_doc_approval --> doc_drafting: H1 驳回
    rebuilding --> rebuilding: 一致性失败 且 尝试 < 5
    rebuilding --> manual_review: MRF-3002
    rebuilding --> parity_passed
    parity_passed --> usability_run
    usability_run --> awaiting_signoff: 验证报告生成
    awaiting_signoff --> deployed: H2 签核
    awaiting_signoff --> rebuilding: H2 驳回
    deployed --> monitoring
    monitoring --> usability_run: PSI > 0.25 / Gini 降 > 5 点
    manual_review --> classified: 人工修正后恢复
    manual_review --> doc_drafting
    manual_review --> rebuilding
    manual_review --> failed
```

## 关键约定

| 主题 | 约定 | 位置 |
| --- | --- | --- |
| 响应 | 统一信封，`status` ∈ success/accepted/error，`errors`/`warnings` 恒为数组 | `mrf.core.envelope` |
| 返回码 | MRF-0000 … MRF-5000 | `mrf.core.codes` |
| 状态 | 13 个状态 + 允许的迁移表 | `mrf.core.states` |
| 阈值 | 置信度 0.7、说明书 3 次、一致性 5 次、通过分 80、PSI 0.10/0.25 | `config/pipeline.yaml` |
| 模块接口 | Classifier / DocWriter / Rater / Rebuilder / ModelRunner / ReportBuilder / DataQualityChecker / MonitoringRegistrar | `mrf.contracts.agents` |
| 取数 | 智能体只通过 7 个 MCP 工具取数，不自己算数字 | `mrf.mcp_server.tools` |
| 两类重试 | 质量重试由编排器计数；LLM 瞬时错误在 `mrf.llm` 内按 1s/2s/4s+抖动 退让，不占质量重试次数 | A1 设计文档 |
