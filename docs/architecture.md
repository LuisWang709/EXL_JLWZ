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
      Q["任务执行器<br/>asyncio 队列 + jobs 表<br/>A1"]
      G["LangGraph 编排器<br/>状态机·重试·H1/H2<br/>A1"]
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
    R --> Q --> G
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
|---|---|---|
| 响应 | 统一信封，`status` ∈ success/accepted/error，`errors`/`warnings` 恒为数组 | `mrf.core.envelope` |
| 返回码 | MRF-0000 … MRF-5000 | `mrf.core.codes` |
| 状态 | 13 个状态 + 允许的迁移表 | `mrf.core.states` |
| 阈值 | 置信度 0.7、说明书 3 次、一致性 5 次、通过分 80、PSI 0.10/0.25 | `config/pipeline.yaml` |
| 模块接口 | Classifier / DocWriter / Rater / Rebuilder / ModelRunner / ReportBuilder / DataQualityChecker / MonitoringRegistrar | `mrf.contracts.agents` |
| 取数 | 智能体只通过 7 个 MCP 工具取数，不自己算数字 | `mrf.mcp_server.tools` |
| 两类重试 | 质量重试由编排器计数；LLM 瞬时错误在 `mrf.llm` 内按 1s/2s/4s+抖动 退让，不占质量重试次数 | A1 设计文档 |
