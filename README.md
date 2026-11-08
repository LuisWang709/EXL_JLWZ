# Model Risk Factory（智能体模型风险工厂）— EXL Hackathon C04 · A 队

A 队的模型风险工厂。它把一份遗留的 SAS / R 模型代码，自动处理为 **清单记录 → SS1/23 说明书 → 评级 → Python 重建与逐笔一致性证明 → 可用性运行与验证报告 → 部署与持续监控**。流程中有 2 道人工关卡（H1 说明书批准、H2 验证签核）。

> 执行计划：[C04 A队执行计划 — 智能体模型风险工厂.md](C04%20A队执行计划%20—%20智能体模型风险工厂.md) · API 契约：[openapi.yaml](openapi.yaml) · 分工与接口：[docs/team/](docs/team/README.md) · 架构：[docs/architecture.md](docs/architecture.md)

## 快速开始

需要 Python 3.11–3.13 和 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync                                  # 核心依赖 + dev 工具
uv sync --extra data --extra rag         # 按需加装：数据/建模、RAG、azure、mlops、ui；全部：--all-extras
cp .env.example .env                     # 默认 MRF_LLM_PROVIDER=mock，不需要任何密钥
uv run pytest                            # 单元测试（模拟 LLM）
uv run uvicorn mrf.api.app:app --reload  # http://localhost:8000/docs ，健康检查 /healthz
uv run python -m mrf.run --model M001 --auto-approve   # 本地用 stub 跑完整流水线
uv run pre-commit install                # 一次即可
```

## 仓库结构

```text
openapi.yaml               统一 REST API 契约 v1（A1 审批变更）
config/pipeline.yaml       所有阈值：置信度、重试次数、评级分数线、一致性容差、PSI 阈值
src/mrf/
  core/                    响应信封、返回码 MRF-xxxx、流水线状态机               A1
  contracts/               共享领域模型 + 各模块接口 Protocol（冻结）            A1
  api/                     FastAPI 应用、/api/v1 路由、任务执行器                A1
  orchestrator/            LangGraph 状态机、重试策略、H1/H2 关卡、审计          A1
  llm/                     LLM 封装：指数退让、token/费用、mock                  A1
  storage/                 Repository（SQLite / Cosmos）、Blob                   A1
  mcp_server/              MCP 工具服务（/mcp），tools/ 下每个工具归各自负责人    A1 框架
  agents/classify/         模型识别智能体                                        A1
  data/                    读取任意格式、清洗、pandera schema                    A2
  agents/rebuild/          SAS/R → Python 重建 + 一致性                          A2
  rag/                     知识库（SS1/23、模板、映射表）                        A3
  agents/doc/              说明书智能体                                          A3
  rating/                  评级器（规则 60 + LLM 评审 40）                       A3
  validation/              AUC/Gini/KS/Brier/HL/PSI/CSI/公平性                   A3
  reporting/               分析报告、验证报告                                    A3
  monitoring/              数据质量、漂移、告警、定期报告                        A4
  ui/                      Streamlit 界面                                        A4
models/legacy/             “遗留”模型 M001–M004                                 A2
tests/{unit,integration,fixtures}                                               全员（fixtures: A2）
templates/                 说明书/报告/证书 Jinja 模板                           A3（证书 A2，监控 A4）
kb/                        RAG 原始资料                                          A3
infra/  docker/  .github/  Bicep、Dockerfile、CI/CD                              A4
docs/                      架构、分工、设计文档、评估、RAI 说明
data/                      本地数据（git 忽略）
```

## 团队

| 成员 | 角色 | 负责 | 任务书 |
| --- | --- | --- | --- |
| A1 Albert | 队长、智能体架构师 | 编排器、API、识别、MCP 框架、集成 | [A1.md](docs/team/A1.md) |
| A2 | 建模与重建 | 遗留模型、数据清洗、重建、一致性 | [A2.md](docs/team/A2.md) |
| A3 | 文档、验证与 RAI | RAG、说明书、评级、验证、报告 | [A3.md](docs/team/A3.md) |
| A4 | DevOps、监控与展示 | CI/CD、Azure、监控、界面、视频/PPT | [A4.md](docs/team/A4.md) |

协作规则见 [CONTRIBUTING.md](CONTRIBUTING.md)；把自己的模块接入流水线见 [docs/team/integration.md](docs/team/integration.md)。

## AI 工具声明

本仓库在开发过程中使用了 AI 编程助手（Claude Code）辅助生成骨架与文档，所有内容均经队员审阅。完整声明在提交前补充于 `docs/ai_disclosure.md`（A1）。
