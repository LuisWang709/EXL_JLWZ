# 协作规则

## 分支

| 分支 | 用途 |
| --- | --- |
| `main` | 受保护；只接受 PR；合并即自动部署 dev（A4 的 CD 上线后） |
| `feat/a1-*` `feat/a2-*` `feat/a3-*` `feat/a4-*` | 个人功能分支，从 `main` 拉出，小步提交，尽快开 PR |
| `fix/*` | 修 bug |
| tag `v*` | 部署 demo 环境；`v1.0.0` 为提交版本 |

```bash
git switch main && git pull
git switch -c feat/a2-parity-suite
# ... commit ...
git push -u origin feat/a2-parity-suite   # 然后在 GitHub 开 PR
```

## 提交信息

`<type>(<scope>): <summary>`，type 取 `feat` `fix` `docs` `test` `refactor` `chore` `ci`，scope 用模块名，例如 `feat(orchestrator): add parity retry loop`。

## PR 与评审

- CI 必须绿：ruff、mypy、pytest（mock LLM）。
- 评审搭档：A1↔A2、A3↔A4，12 小时内完成。
- **契约文件**（`openapi.yaml`、`src/mrf/contracts/`、`src/mrf/core/`、`config/pipeline.yaml`）的任何改动都必须由 A1 批准。只允许新增可选字段；删字段、改字段名要走 `/api/v2`。
- 每天 21:00 站会前，把当天的交付以 PR 或链接形式贴到看板。

## 代码约定

- 跨模块只通过 `mrf.contracts.agents` 中的 Protocol 和 MCP 工具对接，不直接 import 别人的内部实现。
- 失败统一 `raise MRFError(MRFCode.X, ...)`，不要返回 `None` 或裸异常。
- 阈值只从 `mrf.config.get_policy()` 读取，不要写死在代码里。
- 智能体不自己计算数字：所有数字都来自工具（MCP）或 MLflow。
- 只有 A1 的编排器负责重试计数；LLM 的瞬时错误重试已在 `mrf.llm` 里统一处理。
- 真实数据、密钥、`.env` 永远不进 git。测试夹具放 `tests/fixtures/`，每个 < 1 MB。
- 测试默认使用 mock LLM；调用真实 LLM 的测试标 `@pytest.mark.llm`，CI 不跑。
