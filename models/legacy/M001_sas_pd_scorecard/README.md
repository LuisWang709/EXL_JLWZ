# M001 - Retail application PD scorecard (SAS)

| | |
| --- | --- |
| Language / procedure | SAS, `PROC LOGISTIC` (logit link, reference coding) |
| Purpose | probability of default at application |
| Data | German Credit (UCI Statlog), `scripts/get_data.py` + `scripts/preprocess_german_credit.py` |
| Target | `default_flag` (1 = bad credit) |
| Variables | `checking_status` (ref A14), `credit_history` (ref A34), `age_band` (ref 3), `duration_months`, `log_amount` |
| Role | **primary rebuild target** |

The legacy run is simulated (no SAS licence in the team): `scripts/build_m001_legacy.py` fits the same model
specification in Python and writes the exports a SAS run would produce to `tests/fixtures/m001/`
(input sample, legacy scores, parameter estimates, manifest). The fit there is scikit-learn's default
(L2-regularised) logistic regression, so the estimates are not exactly what `PROC LOGISTIC` would print;
parity is tested against those exported scores, which is what matters for the rebuild.
