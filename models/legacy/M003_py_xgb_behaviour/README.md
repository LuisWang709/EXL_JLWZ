# M003 - Behavioural score (Python, XGBoost)

| | |
| --- | --- |
| Language / library | Python, `xgboost.XGBClassifier` |
| Purpose | behavioural score for existing customers |
| Data | Give Me Some Credit (Kaggle; manual download, not redistributed) |
| Target | `serious_dlq_2yrs` |
| Role | documentation and inventory only |

The source is already Python, so the factory does not translate it: the rebuild step records
"no translation required" and no parity certificate is issued. The Kaggle data is not downloaded by
`scripts/get_data.py`, so there is no usability run for this model.
