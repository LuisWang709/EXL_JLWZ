# R / SAS 红黄绿模型验证测试包

六个完全合成的逻辑回归模型包。每个语言各有 green、amber、red 三档，名称包含预期颜色与 Gini 范围。
这是模型验证报告的等级，不是说明书的 0–100 分评级，也不是监控批次的漂移等级。

| 模型名称 | 预期验证等级 | Gini 范围 |
| --- | --- | --- |
| `SIM_R_GREEN_GINI_GE_040` | 绿 | ≥ 0.40 |
| `SIM_R_AMBER_GINI_030_040` | 黄 | ≥ 0.30 且 < 0.40 |
| `SIM_R_RED_GINI_LT_030` | 红 | < 0.30 |
| `SIM_SAS_GREEN_GINI_GE_040` | 绿 | ≥ 0.40 |
| `SIM_SAS_AMBER_GINI_030_040` | 黄 | ≥ 0.30 且 < 0.40 |
| `SIM_SAS_RED_GINI_LT_030` | 红 | < 0.30 |

## 使用方法

仓库已经包含解压后的全部文件，无需重新生成或解压：

```text
models/synthetic_validation/
├── R/       # R：GREEN / AMBER / RED 三个模型包
├── SAS/     # SAS：GREEN / AMBER / RED 三个模型包
├── index.json
└── verification.json
```

1. 在 `R/` 或 `SAS/` 下选一个模型文件夹（若使用下载 ZIP，先解压）。
2. 在“Start a new model”里，模型名使用对应文件夹名；“Model code”同时选择 `upload_together` 下的全部五个文件：R / SAS 代码、manifest、参数、样本输入和参考评分。
3. “Development data”上传 `development.csv`；“Hold-out / out-of-time data”上传 `validation.csv`。
4. schema 选择 `(none)`，这些字段不是 German Credit 的字段。
5. 正常通过 H1 后，在 H2 查看分析 / 验证报告，核对预期颜色和指标。黄色和红色是模型表现不足，不是代码错误或重建失败；按实际审核决定处理。

总 ZIP 用于分发。当前重建器按独立文件识别参考包，请先解压并按上述方式多文件上传。
只上传 R / SAS 代码而不上传参考包或验证数据，会缺少一致性 / 评分证据，不能保证得到预期颜色。
`validation_report.html` 可直接打开预览实测报告；`verification.json` 记录实际评分和各维度颜色。

## 合成设计与边界

- 当前阈值来自项目的 `config/pipeline.yaml`。生成器选择固定种子，使开发、验证两个数据集都落入目标 Gini 档位，校准 HL 检验不降档、评分 PSI 保持绿色。
- 每个数据集有 900 行；三个 age_band 组使用相同的合成特征与标签分布，使公平性保持绿色，便于单独观察表现等级。组内匹配副本不用于估计真实客户泛化能力。
- R/SAS 同色配对使用相同的固定参数和合成数据，适合检查两种代码格式是否被一致处理。参考评分由 Python 按固定公式生成；没有宣称经过原生 R/SAS 引擎或真实客户数据独立验证。
- 说明书仍由实际选择的 LLM 生成、评级，不能从模型名称强制得分。低 Gini 模型的说明书仍可以写得完整并通过 H1。
- `--verify` 在独立的本地内存库和临时文件目录中运行，LLM 为 mock；静态解析、重建、沙箱一致性、逐笔评分和报告渲染均使用项目真实实现。只自动通过测试 H1，停在 H2，不部署这些模型。
- 真实 LLM 若无法正确重建、修改阈值或换数据后，必须以新生成的实际报告为准。

重新生成并校验：

```bash
uv run --extra data python scripts/generate_validation_models.py --verify --out output/test_models_new
```

输出目录必须是新目录；不会覆盖既有模型或队友数据。
