# 运行配置

默认只维护两条验收路径。可选适配器保留兼容性，单独验收，不要求每次演示都启用。

| 路径 | 配置 / 依赖 | 数据与任务 |
| --- | --- | --- |
| 本地开发与演示 | `uv sync --extra data --extra ui --frozen`；`MRF_ENV=local`；SQLite；mock LLM | 本地文件、SQLite 业务库和检查点，API 内后台任务；mock 结果不可当真实 LLM KPI |
| Azure dev / demo | Dockerfile 已安装 data/azure/mlops；Cosmos、托管身份、Azure OpenAI | Azure Files 保存文件与检查点（SQLite 使用 DELETE journal），单副本 API 执行后台任务；定时容器调用 API |

前端只通过 REST API 获取数据和监控阈值，不再单独读取一份本地监控配置。修改阈值后重启 API；修改单个模型的 schedule 可直接通过监控页保存。

可选功能：

- `--extra mlops`：额外记录 MLflow 实验。未安装也可评分；默认 SQLite，可显式指定 tracking URI。
- `MRF_BLOB_ACCOUNT_URL`：Azure Blob 文件适配器，设置后需要额外的权限与容器验收；默认仍使用本地 / Azure Files。
- `--extra rag`：可选 FAISS 加速检索；未安装时使用 numpy 本地索引。Azure AI Search 尚未实现。
- `MRF_TOOL_TRANSPORT=http`：远程 MCP 调试；默认 inprocess，不额外部署一个工具服务。
- `MRF_STUBS` / `Registry.stubs`：本地显式实验 / 测试替身，云环境禁止；缺少真实实现一律失败，不隐式切换。

全部适配器的开发 / CI 检查继续使用 `uv sync --all-extras --frozen`。默认路径改变不删除现有适配器，也不改变 REST / Protocol 的已有调用方式。

单次评分或监控批次共享数据快照，跨操作不缓存文件。分析与验证报告共享同一次事实收集，各自渲染、校验数字和保存；H2 签核仍独立保留。

云部署、真实 LLM、原系统参考评分的剩余验收依赖统一记录在 [完成状态](completion-status.md)。
