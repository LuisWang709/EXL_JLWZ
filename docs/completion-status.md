# 完成状态与外部依赖（2026-11-12）

本次按当前工作区和执行计划检查，数据团队的建模定义、真实原系统参考导出与人工签核不代为决定。
“实现”与“本地验证”不等于“已部署验收”。

## 本次已处理

| 项目 | 结果 / 证据 |
| --- | --- |
| PR 的 CI 根因 | 构建上下文放行 `tests/fixtures`；修复 Ruff 超长行；后续 CI 新增镜像内夹具和真实模块检查 |
| 重建 UI 缺入口 | 新增独立重建表单、状态刷新、任务失败提示、代码下载；UI 连接真实 API 的回归测试覆盖成功和错误夹具 |
| 测试数据交付 | 原包保留；补入 `data/raw` 的两份 CSV 和字段说明；已有二进制文件哈希一致未覆盖；数据包被 git / Docker 排除 |
| 三个重建模型 | M001/M002/M004 的 Python 代码、一致性证书与清洗后开发 / 测试集评分都在隔离 API 中成功，见 `submission/rebuild-verification.json` |
| 重建引用安全 | 显式指定的 rebuild 必须属于当前模型且已通过 parity；显式错误 fixture 不再悄悄回退 |
| Azure Blob 占位实现 | 实现托管身份写入、读取、存在检查及文件快照；连接数据 / 评分读取器；无网络替身测试覆盖 |
| 云端误用 stub | dev/demo 禁用强制 stub 和缺失模块回退；`/readyz` 新增模块加载检查 |
| 监控 cron | 接口复用实际 cron 解析器，非法范围与零步长在保存前拒绝 |
| MLflow | 尊重显式 `MLFLOW_TRACKING_URI`，默认 SQLite；移除 Docker / ACA 中强制使用已弃用文件存储的配置 |
| 评估可信度 | strict 退出码、拒绝 mock、完整数据评分标识、HTTP 错误检查、独立报告输出；无数据评分的流程不标成完整验收 |
| 夜间评估 | 新增 `nightly-eval.yml`，真实 LLM 检查、单模型评估、证据上传；需配置变量后手动首跑再开启定时 |
| 文档校正 | 更新过时的 stub / profiling 描述；SS1/23 现行版本索引、25 题答辩；公平性年龄标签与实际 SAS / 数据分箱对齐 |
| 提交材料 | 10 页审阅 PDF、一页架构图、一页 RAI；逐页内容与讲稿、演示分镜、人工基线表、邮件草稿均在 `submission/` |

## 尚不能完成 / 需要负责人确认

| 项目 | 缺少的条件 / 后续动作 |
| --- | --- |
| 真实 LLM 校准与端到端数字 | 当前环境为 mock，未配置可用 endpoint / 密钥；提供 dev API URL 和凭据后运行校准与评估，不能拿 mock KPI 替代 |
| 云端部署与 demo 冻结 | 本机 Azure CLI 不可用；Docker daemon 未运行。需在有权限的环境验收 API/UI 镜像、Cosmos/托管身份和定时任务，再决定 release tag。原 PR #26 已合并且 CI 成功；本轮另开后续 PR 复验 |
| 云预算与告警运维 | 需确认订阅币种、收件人、阈值、通知渠道；App Insights 遥测已接入，Azure Monitor 告警规则与工作簿尚未在仓库实现 / 验收 |
| M003 Python 模型评分 | 原始包只有 German Credit / 台湾信用卡；缺 Give Me Some Credit 数据、训练后模型与参考评分。现有脚本是训练代码，当前为说明书流程 |
| 独立 SAS/R 一致性验收 | 现有演示参考分数由 Python 复现，需要原系统导出的参数、逐笔评分和来源确认；不覆盖现有演示夹具来伪造独立证明 |
| 人工基线与收益 | 必须由人真实计时，再由 A1 批准写入配置；当前不宣称节省比例或 ROI |
| 数据 / 公平性 / 监管解释签核 | A2 核实来源、许可、字段、目标定义与原系统行为；A3 决定公平性缓释、确认阈值和 RAI；不能用自动脚本冒充这些决定 |
| SS1/23 官方全文入库 | 已核对官方现行版本索引并附 PDF 链接；原文使用条款与逐段解读仍需 A3 确认。目前 KB 保留团队摘要 |
| 可编辑 PPTX | 演示文稿技能要求使用 `@oai/artifact-tool`，但该运行时和依赖加载工具不可用；已交付静态 PDF 与完整源内容 |
| 正式演示视频与发布 | 分镜 / 旁白已写好；需在最终环境录制、审查敏感信息，并提供可公开访问的上传地址 |
| 成员声明、邮件与正式发布 | 成员确认自己的 AI 使用范围；队长填写赛事正式收件人和最终链接后发送并存档；当前只有草稿，没有冒充发送或审阅 |

## 可选扩展（当前已有可用替代实现）

- Azure AI Search 适配器尚未实现。当前部署使用确定性的本地 TF-IDF（numpy / 可选 FAISS），并非缺少知识库检索。
- RDS/RData 读取器和 SQL 数据源尚未接入；本次交付包的 CSV/XLS 可用。这些数据适配工作继续由数据负责人处理。
- 多租户强隔离沙箱、外部队列和多副本 API 属于后续生产化工作。当前是单副本、API key 鉴权的演示系统。

## 复验命令

最终本地结果：Ruff、mypy、Bandit 中高危扫描通过；pytest **296 passed**。
新增的重建页测试会启动真实重建 job，并验证证书、代码和错误夹具提示，而非仅检查按钮存在。

```bash
uv sync --all-extras --frozen
uv run ruff check .
uv run mypy
uv run pytest -q
uv run bandit -c pyproject.toml -r src -ll --skip B608
docker build -f docker/Dockerfile.api -t mrf-api:verify .
```

Windows 沙箱若无权使用系统临时目录，可将 TEMP/TMP 和 pytest 的 `--basetemp` 指到工作区的 `.tmp/`。
本次测试记录在 `.tmp/project-completion/junit-final.xml`；数据文件与运行期数据库均没有加入 git。

真实环境首跑请用 `scripts/evaluate.py --api <dev> --model M001 --dataset <development-id> --dataset <test-id>
--runs 5 --strict --require-real-llm --report-out var/eval/evaluation.md`；API key 从 `MRF_EVAL_API_KEY` 环境变量读取。

外部依据：[SS1/23 现行版本索引](https://www.bankofengland.co.uk/prudential-regulation/publication/2023/may/model-risk-management-principles-for-banks-ss)、
[Azure Blob SDK](https://learn.microsoft.com/en-us/python/api/azure-storage-blob/azure.storage.blob.containerclient?view=azure-python)。
