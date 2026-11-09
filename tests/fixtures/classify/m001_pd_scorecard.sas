/*******************************************************************
 * M001 - Retail application PD scorecard (synthetic legacy model)
 * Owner: Credit Risk Modelling.  Data: German Credit (clean)
 *******************************************************************/
%let dev = work.german_credit_train;

* derive model variables;
data work.model_input;
  set &dev;
  log_amount = log(credit_amount);
  if age < 30 then age_band = 1;
  else if age < 45 then age_band = 2;
  else age_band = 3;
run;

proc logistic data=work.model_input outmodel=work.m001_pd descending;
  class checking_status(ref='A14') credit_history(ref='A34') age_band(ref='3') / param=ref;
  model default_flag(event='1') = checking_status credit_history age_band
                                  duration_months log_amount / link=logit;
  output out=work.scored p=pd_legacy;
run;

proc score data=work.model_input score=work.m001_pd out=work.final;
run;
