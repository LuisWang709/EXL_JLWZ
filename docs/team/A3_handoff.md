# A3 交接说明（分支 `feat/a3-catchup`）

> 这个分支由 A4（LuisWang709）用 Claude 代写，覆盖了 A3 任务书里所有能写成代码的部分。
> **A3 的工作从"写"变成"审 + 做需要人判断的事"**：下面第 3 节按顺序列出。
> 提交包里的 AI 工具声明（计划中 A1 11/12 的任务）需要写明：这个分支的代码和文档草稿由 AI 生成，经 A3 审阅。

## 1. 分支里已经完成的

| 任务书条目 | 文件 | 状态 |
| --- | --- | --- |
| 11/6 验证工具库 | `src/mrf/validation/metrics.py` | 8 个函数，签名未改；对照 scikit-learn / scipy / 手算值的单测 |
| 11/6 `compute_metrics` | `src/mrf/mcp_server/tools/metrics.py` | 读已注册数据集，算所有适用指标；不适用的给 warning |
| 11/3 RAG + `search_kb` | `src/mrf/rag/store.py`、`kb/` | TF-IDF + FAISS（没装 FAISS 就用 numpy），不依赖 embedding 接口，kb/ 文件变动后自动重建 |
| 11/2 模板与评级标准 | `templates/model_doc.md.j2`、`src/mrf/rating/rubric.yaml` | rubric v1，测试会核对它和 `config/pipeline.yaml` 一致 |
| 11/4 说明书智能体 | `src/mrf/agents/doc/agent.py` | 8 个章节；每条论断带 [E#] 证据；LLM 写的句子先过滤（编造的数字/变量直接丢弃） |
| 11/5 评级器 | `src/mrf/rating/rater.py`、`checks.py` | 规则 60 分 + 独立 LLM 评审 40 分 + 两个一票否决；代码和知识库引文逐条核对原文 |
| 11/5 校准 | `tests/unit/test_rater.py`、`scripts/calibrate_rater.py` | mock 下：好样本 93 分通过；缺章节、无证据、编造变量、编造数字、空话 5 种坏样本全部不通过 |
| documents API | `src/mrf/api/routers/documents.py` | 4 个端点；POST 是 job（起草→评级→按意见重写，最多 3 次） |
| 11/8–9 报告生成器 | `src/mrf/reporting/builder.py`、`templates/*_report.html.j2` | 分析报告 + 验证报告（H2 签核包）；每个数字记录来源并在渲染后核对，不一致就拒绝保存 |
| reports API | `src/mrf/api/routers/reports.py` | 列表（按 type 过滤）、详情、`?format=html` 直接返回报告页面 |
| 11/10 公平性专题 | `docs/fairness_m001.md`、`scripts/fairness_m001.py` | **草稿**；数字来自 300 行夹具 |
| 11/11 RAI 说明 | `docs/responsible_ai.md` | **草稿** |
| 11/12–13 签核 / 问答 | `scripts/export_report_numbers.py`、`docs/ss1_23_qa.md` | 导出脚本可用；问答是**草稿** |

全流程已接通：`python -m mrf.run` 和 `tests/integration/test_mvp_flow.py` 现在用的是真实的 DocAgent / DocRater / ReportBuilderImpl。
本地检查全部通过：ruff、mypy、pytest、bandit。

## 2. 先跑起来（10 分钟）

```bash
git fetch origin && git checkout feat/a3-catchup
uv sync --all-extras
uv run pytest -q
uv run python -m mrf.run --model tests/fixtures/classify/m001_pd_scorecard.sas --auto-approve
uv run python scripts/calibrate_rater.py --show-doc     # 看一份 M001 说明书 + 校准结果
uv run python scripts/build_kb.py "model documentation" --collection ss1_23
```

## 3. A3 需要人工完成的事（按顺序）

1. **审 PR（今天）。** 你和 A4 是这些目录的 CODEOWNER；A4 是作者，所以需要你批准。重点看：
   `agents/doc/agent.py`（说明书怎么生成）、`rating/checks.py`（规则分怎么算）、`reporting/builder.py`（红黄绿规则）、
   `kb/ss1_23/ss1_23_principles_summary.md`（SS1/23 转述是否准确）。答辩时这些都要你来讲。
2. **放入 SS1/23 官方原文。** 现在 `kb/ss1_23/` 里只有团队自写的转述（文件头已注明"not the official text"）。
   从 PRA 官网下载 PDF，确认使用条款允许放进仓库，然后：
   ```bash
   uv run --with pypdf python scripts/import_kb_pdf.py ~/Downloads/ss123.pdf --collection ss1_23 \
       --source "PRA SS1/23 - Model risk management principles for banks (official text)" \
       --url https://www.bankofengland.co.uk/prudential-regulation/publication/2023/may/model-risk-management-principles-for-banks-ss \
       --licence "<你核实过的条款>"
   uv run python scripts/build_kb.py "documentation independent third party" --collection ss1_23
   ```
   不能放进仓库的话，就只在本地/部署时放，并在 README 里说明。
3. **和 A2 对齐映射笔记。** `kb/mapping/sas_r_python_differences.md` 是我写的通用差异清单，和 A2 的映射表合并或互相引用。
4. **用真实 LLM 校准（最重要）。** CI 用的是 mock；真实模型的表现只有在本机跑才知道。用和演示环境**相同**的 LLM 配置
   （A4 的 `feat/a4-azure-openai` 分支正在接 Azure OpenAI gpt-5-mini；变量名见 `.env.example`），例如：
   ```bash
   # Azure OpenAI
   MRF_LLM_PROVIDER=azure_openai MRF_LLM_MODEL=<部署名> AZURE_OPENAI_ENDPOINT=https://<资源名>.openai.azure.com \
   AZURE_OPENAI_API_KEY=... uv run python scripts/calibrate_rater.py --show-doc
   # 或 DeepSeek
   MRF_LLM_PROVIDER=openai OPENAI_BASE_URL=https://api.deepseek.com MRF_LLM_MODEL=deepseek-chat \
   OPENAI_API_KEY=... uv run python scripts/calibrate_rater.py --show-doc
   ```
   如果想让评审用另一个模型（降低"自己给自己打分"的风险），再加 `MRF_LLM_REVIEWER_MODEL=<另一个部署名>`。
   检查：好样本是否通过、坏样本是否都不通过、说明书里 LLM 加的句子是否准确。需要调的地方：
   `agents/doc/agent.py` 的 `SYSTEM_PROMPT`、`rating/rater.py` 的 `SYSTEM_PROMPT`、`rating/rubric.yaml` 的权重。
   把输出贴给 Claude 也可以帮你调。
5. **确认报告阈值（需要 A1 批准）。** `config/pipeline.yaml` 新增了 `reporting` 段：Gini 0.40/0.30、
   公平性 0.80/0.70（four-fifths rule）、HL p 值 0.05、公平性分段列 `age_band`。这些是团队政策，你确认后让 A1 批准。
   `manual_baseline_hours` 故意留空：A2 11/11 的人工计时出来后再填，否则报告不算节省（避免编数字）。
6. **公平性专题定稿（11/10）。** 用完整的 out-of-time 数据重跑：
   `uv run python scripts/fairness_m001.py --data <清洗后的数据> --scores <评分文件> --score-column <列名> --write`，
   然后改写 `docs/fairness_m001.md` 的解读，在 A–E 里选缓释方案并填写决策记录。
   夹具上的结果：30 岁以下审批率是 45 岁以上的 0.69 倍（低于 0.80），报告显示红灯；年轻组坏账率也更高，但好客户被拒率也更高。
7. **RAI 说明定稿（11/11）。** `docs/responsible_ai.md` 每一句都描述了代码现在的行为；逐句核对部署版本，删掉不再成立的内容。
8. **数字签核（11/12–13）。** `uv run python scripts/export_report_numbers.py --out signoff.csv` 导出所有报告数字及来源；
   PPT 里的数字只从这个文件抄，逐条打勾。（MLflow 还没接上，签核以报告为准。）
9. **SS1/23 问答准备。** `docs/ss1_23_qa.md` 有 15 个问答草稿；对照官方原文核实，并且要能脱稿回答。

## 4. 需要其他人配合

- **A1**：批准 `config/pipeline.yaml` 的 `reporting` 段；`openapi.yaml` 可以补充两处（新增，不破坏 v1）：
  `GET .../documents/{doc_id}?format=markdown|html` 直接返回 text/markdown、text/html；
  `GET .../reports/{report_id}` 新增 `format=html`。另外改了 `tests/integration/test_mvp_flow.py`（断言 A3 模块是真实实现）和
  `tests/unit/test_mcp.py`（原来用 `search_kb` 当"未实现"的例子，现在换成测试内的假工具）。
- **A2**：
  - `profile_data` 实现后，说明书的数据章节会自动用上（现在显示"not available"）。
  - 可用性运行请把指标写进 `Run.metrics`，键名用 `auc`、`gini`、`ks`、`brier`、`psi_score`、`hosmer_lemeshow`（直接用 `compute_metrics` 的结果即可）。
  - 输出文件里的分数列请用 `pd_python`（或 `frames.SCORE_COLUMNS` 里的名字），行顺序和数据集一致，报告才能算公平性。
- **A4**：监控报告由 `mrf.monitoring.report:MonitoringReportBuilder` 提供时，`ReportBuilderImpl` 会自动转交；
  UI 可以直接嵌入 `?format=html` 的说明书和报告。

## 5. 设计取舍与已知限制

- 说明书的确定性句子（链接函数、事件定义、CLASS 编码、分段切点）是针对 SAS 写的规则；R / Python 模型这类句子更少，主要靠 LLM 补充。
- 评级的数字检查不检查 10 以内的整数（`rubric.yaml` `numbers.small_integer_limit`），避免把"3 次尝试""Principle 4"误判为编造。
- 公平性默认决策阈值 = 让整体拒绝率等于观察到的坏账率；真实的业务 cut-off 确定后应替换。
- 报告数字核对失败时不保存报告，流水线转人工审核（MRF-5000）。
- 知识库检索是 TF-IDF：确定、离线可跑，但对换了说法的问题召回较弱。
