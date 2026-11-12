# 评估结果 / Evaluation

生成时间 20261112T103708Z · 目标 `local` · LLM `mock` / `gpt-4o-mini` · 每个模型 5 次 · commit `8ae1b07`

> **不可用于报告**：本次使用了 mock / 未知 LLM 或 stub 智能体（stub：无）。只验证评估脚本本身，数字不得进入 PPT。

由 `scripts/evaluate.py` 生成，原始数据见 `var/eval/20261112T103708Z.json`。H1/H2 在评估中自动批准；“智能体耗时”不含在人工关卡的等待时间。

| 模型 | 次数 | 到达监控 | 转人工 | 识别准确率 | 智能体耗时中位数 (s) | 说明书尝试 | 一致性尝试 | LLM 调用 | tokens | 费用 (EUR) | 退让次数 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| M001 | 5 | 5 | 0 | 100% | 0.708 | 1 | 1 | 4 | 9271 | 0.00159 | 0 |
| M002 | 5 | 5 | 0 | 100% | 0.702 | 1 | 1 | 4 | 7740 | 0.00138 | 0 |
| M003 | 5 | 5 | 0 | 100% | 0.097 | 1 | 1 | 3 | 6100 | 0.00115 | 0 |
| M004 | 5 | 5 | 0 | 100% | 0.707 | 1 | 1 | 4 | 8072 | 0.00142 | 0 |

智能体实现：`{"classifier": "ClassifierAgent", "doc_writer": "DocAgent", "rater": "DocRater", "rebuilder": "RebuildAgent", "runner": "ModelRunnerImpl", "report_builder": "ReportBuilderImpl", "quality_checker": "QualityCheckerImpl", "monitoring": "MonitoringRegistrarImpl"}`
