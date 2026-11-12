# M002 - Credit card default model (R)

| | |
| --- | --- |
| Language / function | R, `glm(family = binomial(link = "logit"))`, treatment contrasts |
| Purpose | probability of default next month (existing card accounts) |
| Data | Default of Credit Card Clients, Taiwan (UCI), `scripts/get_data.py` |
| Target | `default_next_month` |
| Variables | `limit_bal`, `util` (= `bill_amt1 / max(limit_bal, 1)`), `pay_0`, `pay_2`, `age`, `education` (ref 2) |
| Role | second rebuild target |

The legacy run is simulated: `scripts/build_legacy_fixtures.py` fits the same specification with an unpenalised
binomial GLM (statsmodels; the same maximum-likelihood fit R `glm` computes) and writes the exports to
`tests/fixtures/m002/` (500 hold-out records).
