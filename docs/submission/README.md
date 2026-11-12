# 提交材料

当前为可审阅版本，待真实 LLM 验收、数据负责人复核与人工签核后定稿。

| 材料 | 文件 / 生成结果 | 状态 |
| --- | --- | --- |
| 10 页方案内容与逐页讲稿 | `deck.json` | 内容已整理；未包含模拟 KPI 或未经测量的收益 |
| 方案 PDF | `output/pdf/model-risk-factory-review.pdf` | `scripts/build_submission.py` 生成 |
| 一页架构图 | `output/pdf/architecture.pdf` | 同上；源于当前代码结构 |
| 一页 RAI | `responsible-ai.md`、`output/pdf/responsible-ai.pdf` | 技术说明可审阅；监管 / 公平性决策仍需 A3 |
| 3 分钟演示脚本 | `demo-script.md` | 脚本就绪；正式录屏和上传未完成 |
| 商业基线记录表 | `manual-baseline.md` | 模板就绪；需要人实际计时 |
| 提交邮件 | `submission-email.md` | 草稿；收件人、公开链接、成员确认后由队长发送 |
| 答辩准备 | `../ss1_23_qa.md` | 25 题，需各负责人核对与彩排 |

生成 PDF（可在隔离工具环境安装 reportlab）：

```bash
uv run --with reportlab python scripts/build_submission.py
```

PDF 是静态审阅材料。可编辑 PPTX 尚未生成：本会话演示文稿技能指定的
`@oai/artifact-tool` 运行时及 `load_workspace_dependencies` 工具均不可用。
保留 `deck.json` 的逐页内容、讲稿和来源，供具备运行时的环境导出。

正式提交前逐项核对 [完成状态](../completion-status.md)，不要把“代码已实现”写成“云端已验收”。
