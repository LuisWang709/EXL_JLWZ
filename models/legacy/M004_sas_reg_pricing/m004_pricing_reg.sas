/*******************************************************************
 * M004 - Personal loan pricing margin model (legacy model, simulated)
 * Owner : Pricing and Product
 * Data  : loan book extract (SYNTHETIC - derived for the hackathon)
 * Use   : margin over funding cost quoted for a new personal loan
 *******************************************************************/
data work.pricing;
  set lib.loan_book_train;
  term_years = term_months / 12;
run;

data work.pricing_holdout;
  set lib.loan_book_test;
  term_years = term_months / 12;
run;

proc reg data=work.pricing outest=work.m004_est;
  model price_margin = term_years loan_amount risk_grade_num ltv;
quit;

proc score data=work.pricing_holdout score=work.m004_est out=work.m004_scored type=parms;
  var term_years loan_amount risk_grade_num ltv;
run;

/* exports handed to the Model Risk Factory */
proc export data=work.m004_est outfile="coefficients.csv" dbms=csv replace; run;
proc export data=work.m004_scored (keep=id MODEL1 price_margin rename=(MODEL1 = margin_legacy))
            outfile="legacy_scores.csv" dbms=csv replace; run;
