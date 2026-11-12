/*******************************************************************
 * M001 - Retail application PD scorecard (legacy model, simulated)
 * Owner : Credit Risk Modelling
 * Data  : German Credit (UCI Statlog), cleaned extract
 * Use   : probability of default at application, 12-month outcome
 * Output: work.m001_estimates (parameter estimates)
 *         work.m001_scored    (id, pd_legacy) -> parity fixture
 *******************************************************************/
%let dev = clean.german_credit_train;
%let oot = clean.german_credit_test;

/* 1. derive the model variables (same logic for development and scoring) */
%macro derive(in=, out=);
data &out;
  set &in;
  /* loan amount is capped at 15,000 DM before the log transform */
  credit_amount = min(credit_amount, 15000);
  log_amount = log(credit_amount);
  /* age bands: 1 = under 25, 2 = 25 to 39, 3 = 40 and over */
  if age < 25 then age_band = 1;
  else if age < 40 then age_band = 2;
  else age_band = 3;
  /* target: UCI class 2 = bad credit */
  default_flag = (class = 2);
run;
%mend derive;

%derive(in=&dev, out=work.model_input);
%derive(in=&oot, out=work.score_input);

/* 2. fit: logistic regression, reference coding, event = default */
ods output ParameterEstimates = work.m001_estimates;
proc logistic data=work.model_input outmodel=work.m001_pd;
  class checking_status (ref='A14')
        credit_history  (ref='A34')
        age_band        (ref='3') / param=ref;
  model default_flag(event='1') = checking_status credit_history age_band
                                  duration_months log_amount / link=logit;
run;

/* 3. score the hold-out sample with the stored model */
proc logistic inmodel=work.m001_pd;
  score data=work.score_input out=work.m001_scored (rename=(P_1 = pd_legacy));
run;

/* 4. exports handed to the Model Risk Factory */
proc export data=work.m001_estimates outfile="coefficients.csv" dbms=csv replace; run;
proc export data=work.m001_scored (keep=id pd_legacy default_flag)
            outfile="legacy_scores.csv" dbms=csv replace; run;
