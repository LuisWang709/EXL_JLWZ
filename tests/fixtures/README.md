# tests/fixtures (owner: A2)

One folder per legacy model, exported from the original SAS/R run. These are the ground truth for parity tests.

```
tests/fixtures/m001/
  input_sample.*        # small, anonymised/synthetic input rows (any format; csv/parquet preferred)
  legacy_scores.*       # record_id + score exported from SAS/R
  coefficients.json     # parameter estimates (name, value, reference level / coding)
  manifest.json         # {"model_id", "source_language", "record_id_column", "score_column", "tolerance", "format"}
  inventory_gold.json   # hand-written gold inventory record (for classification accuracy)
```

Keep each fixture < 1 MB. Real datasets never go into git (see docs/data.md).
