/*
SIM_SAS_GREEN_GINI_GE_040: simulated probability of default model.
Owner: Synthetic Validation Tests. Target: default_flag, one means default.
Use: local testing only; all records are synthetic and contain no customer information.
Frozen production parameters are supplied in coefficients.json. Do not refit them for the parity test.
The reference fit below is diagnostic; exported scores use the frozen formula.
Limitations: no real portfolio evidence or independent native-engine reference scores.
The age_band groups are matched replicas for controlled fairness testing, not independent customers.
Governance: H1 documentation approval and independent H2 validation sign-off are required.
Monitoring compares future batches with the registered healthy baseline.
*/

proc import datafile="input_sample.csv" out=work.synthetic dbms=csv replace;
  guessingrows=max;
  getnames=yes;
run;

/* Diagnostic fit; the frozen exported model below remains authoritative. */
proc logistic data=work.synthetic;
  model default_flag(event='1') = risk_driver utilisation / link=logit;
run;

data work.legacy_scores;
  set work.synthetic;
  eta = -0.1 + 1.8 * risk_driver + 0.2 * utilisation;
  pd_legacy = 1 / (1 + exp(-eta));
  keep id pd_legacy;
run;

proc export data=work.legacy_scores outfile="legacy_scores.csv" dbms=csv replace;
run;
