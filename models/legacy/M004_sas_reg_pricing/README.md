# M004 - Personal loan pricing margin model (SAS)

| | |
| --- | --- |
| Language / procedure | SAS, `PROC REG` (ordinary least squares) |
| Purpose | pricing: margin over funding cost |
| Data | **synthetic** loan book derived from German Credit with a fixed seed (`scripts/build_legacy_fixtures.py`) |
| Target | `price_margin` |
| Variables | `term_years` (= `term_months / 12`), `loan_amount`, `risk_grade_num`, `ltv` |
| Role | third rebuild target (identity link) |

The data and therefore every number of this model are synthetic; it exists to show that the factory handles a
non-PD, non-logistic model. The exports are in `tests/fixtures/m004/`.
