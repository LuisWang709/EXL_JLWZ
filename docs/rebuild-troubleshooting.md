# Python rebuild 排查与使用

## 当前结论

SAS/R → Python 的后端已经实现：`RebuildAgent` 负责候选代码与反馈，`run_parity` 在受限评分子进程中逐笔比较，
`ModelRunnerImpl` 使用通过一致性的代码评分。原 UI 仅展示历史重建，缺少启动入口；现已补齐启动、任务状态、
失败原因、代码查看与下载。单独重建不会替代 H1/H2 审批，也不会自动推进原流水线。

## UI 里没有结果时

1. 正常流水线必须先在 Review queue 完成 H1，才会进入重建。未过 H1 时没有重建记录是预期行为。
2. 在 Models 选择对应模型，进入 Python rebuild，点击 **Start Python rebuild** 可发起独立任务。
3. fixture ID 留空时从上传的模型包或内置演示包识别。显式填写的 ID 不存在时返回 MRF-1404，不会回退。
4. 使用 **Refresh rebuild status** 查看状态。失败消息区分夹具缺失、沙箱策略、评分崩溃和不一致等原因。
5. 通过后显示一致性证书和代码下载。已有 Python 源码但没有参考评分时，只展示源代码并标记一致性未评估。
6. 若云端仍看到旧页面，需要把此版本部署到对应的 API 与 UI 镜像；本地修改不会自动替换云端容器。

## 原始数据不等于一致性夹具

`raw数据.zip` 包含 German Credit 与台湾信用卡原始数据，已经补入 `data/raw/`。不会因为放在目录里就自动登记到 API。
用现有预处理流程产生 `data/clean/` 后，还需通过 `/api/v1/datasets` 上传登记，并把 dataset ID 关联到流水线。
不要把未生成 `log_amount`、`age_band`、`default_flag` 的原始 German Credit 直接当成 M001 的评分输入。

完整重建包包括源代码、`manifest.json`、`input_sample.csv`、`legacy_scores.csv`，回归模型通常还需要
`coefficients.json`。原始训练表既没有拟合参数，也没有原系统逐笔评分，无法单独证明迁移正确。
模型名 M001/M002/M004 可用内置演示夹具；这不是对任意上传模型的通用编译器。

M003 的现有 Python 文件是训练脚本，依赖 `give_me_some_credit.csv`，并没有可移植的训练后模型或
`score(input_csv)` 入口。当前资料包未提供这些文件，因此 M003 的定位仍是清单 / 说明书，不能声称已验证评分。

## 本次验证

机器可读记录：`docs/submission/rebuild-verification.json`。隔离本地 API，SQLite + mock LLM；演示审批为脚本模拟。

| 模型 | 一致性记录 | 不一致 | 开发集评分行数 | 测试集评分行数 |
| --- | --- | --- | --- | --- |
| M001 | 300 | 0 | 700 | 300 |
| M002 | 500 | 0 | 21000 | 9000 |
| M004（合成定价） | 300 | 0 | 700 | 300 |

三个模型均生成代码和证书。M001 漂移演示后回到 `awaiting_signoff` 是重新验证流程的预期结果。
这些参考值来自 Python 复现，真实 LLM 翻译与 SAS/R 独立运行的有效性仍待单独验收。

附：交付数据字典仍提到旧 SAS 年龄分箱 bug 和 B 队。当前 M001 代码已经使用 `<25 / 25–39 / ≥40`
分箱并修正了链式比较，公平性脚本和说明中的旧 `<30 / 30–44 / ≥45` 标签也已对齐。
