"""M003 - Behavioural score for existing customers (synthetic legacy model)."""

import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split

FEATURES = [
    "revolving_utilization",
    "age",
    "past_due_30_59",
    "debt_ratio",
    "monthly_income",
    "open_credit_lines",
    "past_due_90",
]
TARGET = "serious_dlq_2yrs"

df = pd.read_csv("data/clean/give_me_some_credit.csv")
X_train, X_test, y_train, y_test = train_test_split(df[FEATURES], df[TARGET], test_size=0.3, random_state=42)

model = xgb.XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8)
model.fit(X_train, y_train)
df["bscore"] = model.predict_proba(df[FEATURES])[:, 1]
