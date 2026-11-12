# 演示脚本（目标 2 分 50 秒，留 10 秒余量）

录制前：确认 API `/readyz` 正常、UI 可登录，保存部署 commit、LLM provider/model，关闭通知并隐藏密钥。
使用有明确权限的样本。若使用 mock，开头和视频说明必须标注 mock；不得称为真实 LLM 验收。
先按 `scripts/seed_demo.py` 跑演示准备，再录正常操作。脚本审批仅代表演示，不冒充独立人工签核。

| 时间 | 画面 / 操作 | 英文旁白 |
| --- | --- | --- |
| 0:00–0:20 | Overview 与模型清单 | Model Risk Factory connects legacy code to documentation, validation and monitoring. Each result retains its supporting evidence. |
| 0:20–0:45 | M001 说明书及 evidence，显示评级 | The agent drafts a cited document. Deterministic checks verify the evidence and reject invented variables or unsupported numbers. |
| 0:45–1:05 | Review queue 展示 H1；人工点击批准 | A human approves the documentation. When it needs changes, the reviewer returns comments to the next draft. |
| 1:05–1:35 | Models / Python rebuild，启动或查看重建，打开代码和证书 | The rebuild produces a Python score function and tests each reference record. The certificate binds the result to the generated code hash. Our present legacy fixture scores use Python reproduction. |
| 1:35–2:00 | 验证报告与 H2 | Tool results supply performance, stability and fairness metrics. Missing evidence remains unassessed. A human records the validation decision at H2. |
| 2:00–2:30 | Monitoring：红色漂移、被拒批次及返回验证 | Quality failures reject a batch before scoring. Red drift raises an alert and sends the model back to validation and another sign-off. These monitoring batches are synthetic. |
| 2:30–2:50 | 架构图或最后一页 | The prototype preserves an auditable workflow. Our next acceptance steps are real LLM evaluation, independent legacy exports and a measured manual baseline. |

导出 MP4 后检查：总时长不超过 3 分钟、所有文字可读、旁白与画面对应、无密钥/个人数据泄漏。
上传后用未登录窗口检查访问权限；把真实链接加入提交邮件。当前尚无已录制或已发布的视频链接。
