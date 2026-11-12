# Legacy models

"Legacy" SAS / R / Python models the factory ingests. The legacy runs are simulated in Python (no SAS licence);
each folder says how.

| id | folder | language | algorithm | purpose | role | parity fixture |
| --- | --- | --- | --- | --- | --- | --- |
| M001 | `M001_sas_pd_scorecard/` | SAS | PROC LOGISTIC scorecard | PD | **rebuild target** | `tests/fixtures/m001/` |
| M002 | `M002_r_glm_card_default/` | R | glm(binomial) | credit-card default | second rebuild | `tests/fixtures/m002/` |
| M003 | `M003_py_xgb_behaviour/` | Python | XGBoost | behavioural score | documentation + inventory only | - |
| M004 | `M004_sas_reg_pricing/` | SAS | PROC REG | pricing (synthetic data) | third rebuild | `tests/fixtures/m004/` |

A **legacy model package** is the source code plus the exports a rebuild is proven against:

```text
manifest.json        {"model_id", "record_id_column", "score_column", "link": "logit" | "identity", ...}
input_sample.csv     records the legacy system scored
legacy_scores.csv    record id + legacy score
coefficients.json    parameter estimates: {"intercept": .., "<column>": .., "<column>_<level>": ..}
```

Upload the four files together with the code when starting a pipeline, or name the model `M001` / `M002` /
`M004` to use the built-in fixtures. Rebuild all fixtures: `uv run python scripts/build_m001_legacy.py` and
`uv run --with xlrd python scripts/build_legacy_fixtures.py`.
