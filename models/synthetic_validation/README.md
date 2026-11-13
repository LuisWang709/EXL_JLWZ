# Synthetic R/SAS green, amber, and red validation examples

Six fully synthetic logistic models, with one case per performance level for each language. These are validation-report grades, not document scores or monitoring drift grades.

| Model | Expected grade | Gini |
| --- | --- | --- |
| SIM_R_GREEN_GINI_GE_040 | Green | >= .40 |
| SIM_R_AMBER_GINI_030_040 | Amber | >= .30 and < .40 |
| SIM_R_RED_GINI_LT_030 | Red | < .30 |
| SIM_SAS_GREEN_GINI_GE_040 | Green | >= .40 |
| SIM_SAS_AMBER_GINI_030_040 | Amber | >= .30 and < .40 |
| SIM_SAS_RED_GINI_LT_030 | Red | < .30 |

## Use

All unpacked files are versioned under R/ and SAS/, alongside index.json and verification.json.

1. Choose a model folder under R/ or SAS/; extract downloaded ZIPs first.
2. In Start a new model, use its folder name and upload all five upload_together files: source, manifest, coefficients, inputs, references.
3. Upload development.csv as Development data and validation.csv as Hold-out / out-of-time data.
4. Select schema (none); these are not German Credit columns.
5. After H1, inspect analysis/validation reports at H2. Amber/red means poor model performance, not necessarily broken code or parity. Make the actual review decision accordingly.

The ZIP is for distribution; the rebuilder identifies separate uploaded reference files. Source-only or missing validation data cannot guarantee the expected grade. Open validation_report.html to preview recorded results; verification.json records actual metrics/colors.

## Design and boundaries

- Thresholds come from config/pipeline.yaml. Fixed seeds place development/validation Gini in the intended range, keep HL calibration from downgrading, and keep score PSI green.
- Each dataset has 900 rows. Three age_band groups have matching synthetic features/labels to hold fairness green and isolate performance. Matched copies do not estimate real customer generalization.
- Same-color R/SAS pairs share fixed parameters/data to test consistent handling. Python formulas generated reference scores; no native R/SAS or customer-data independent validation is claimed.
- The selected LLM generates/rates documentation. Names do not force scores. A low-Gini model can still have complete, accurate documentation and pass H1.
- --verify uses isolated local memory/temp storage and mock LLM. Parsing, rebuild, sandbox parity, scoring, reports are real implementations. It simulates H1 and stops at H2, without deployment.
- With real LLM output, changed thresholds, or changed data, use the newly generated actual report.

Regenerate into a new directory, preserving existing team artifacts:

```bash
uv run --extra data python scripts/generate_validation_models.py --verify --out output/test_models_new
```
