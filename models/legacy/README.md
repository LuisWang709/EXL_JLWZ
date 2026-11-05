# Legacy models (owner: A2)

"Legacy" SAS / R / Python models the factory ingests. Each model has its own folder:

| id | folder | language | algorithm | purpose | role |
|----|--------|----------|-----------|---------|------|
| M001 | `M001_sas_pd_scorecard/` | SAS | PROC LOGISTIC scorecard | PD | **rebuild target** |
| M002 | `M002_r_glm_card_default/` | R | glm(binomial) | credit-card default | second rebuild (stretch) |
| M003 | `M003_py_xgb_behaviour/` | Python | XGBoost | behavioural score | doc + inventory only |
| M004 | `M004_sas_reg_pricing/` | SAS | PROC REG | pricing | optional |

Folder layout: `model.<sas|R|py>`, `README.md` (what it is, data used, how it was run), exported outputs go to `tests/fixtures/m00x/`.
