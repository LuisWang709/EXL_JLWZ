/* M004 - Personal loan pricing margin model (synthetic legacy model) */
data work.pricing;
  set lib.loan_book;
  term_years = term_months / 12;
run;

proc reg data=work.pricing outest=work.m004_est;
  model price_margin = term_years loan_amount risk_grade_num ltv;
quit;
