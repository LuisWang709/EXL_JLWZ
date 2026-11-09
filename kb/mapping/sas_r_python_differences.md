---
source: SAS / R / Python behaviour differences that break parity (team notes; align with A2's mapping table)
url: kb/mapping/sas_r_python_differences.md
licence: Team-written for the EXL x UCD hackathon
---

# SAS / R to Python differences that affect parity and documentation

These notes list behaviour differences that commonly make a Python rebuild disagree with a legacy SAS or R
model. The documentation agent cites them in the limitations section; the rebuild agent uses them when a
parity test fails. Always check the options actually used in the legacy code.

## Which outcome is modelled (PROC LOGISTIC)

By default PROC LOGISTIC models the probability of the response value that comes first in sorted order, so
for a 0/1 target it models the probability of 0. The DESCENDING option or EVENT='1' makes it model the
probability of 1. A rebuild that ignores this has coefficients with the opposite sign and scores that equal
one minus the legacy scores. R glm with a binomial family and scikit-learn / statsmodels model the
probability of 1 (the second factor level in R).

## Parameterisation of categorical variables (CLASS statement)

PROC LOGISTIC uses effect coding (PARAM=EFFECT) unless PARAM=REF is given, and the default reference level is
the last level in sorted order. R treatment contrasts use the first factor level as reference, pandas
get_dummies(drop_first=True) drops the first category in sorted order, and statsmodels formulas use the
first level unless C(x, Treatment(reference=...)) is given. Coefficients only match when the coding scheme
and the reference level match; predicted probabilities match under any full-rank coding. Record the
reference level of every categorical variable in the documentation.

## Penalisation and convergence

scikit-learn LogisticRegression applies L2 regularisation by default (C=1.0), which shrinks coefficients;
use penalty=None (or statsmodels Logit) to reproduce unpenalised SAS or R estimates. Different optimisers and
convergence criteria leave differences around the sixth decimal, which is why parity uses an absolute
tolerance on scores rather than exact equality.

## Missing values

In SAS a missing numeric value is smaller than every number, so a condition such as `if x < 30` is true for
missing x and the record falls into the first band. In pandas any comparison with NaN is false, so the same
record falls into the last band. In R a comparison with NA gives NA and ifelse returns NA. PROC LOGISTIC and R
glm (na.action = na.omit) drop records with a missing model variable, while scikit-learn raises an error.
Banding code must reproduce the legacy treatment of missing values explicitly.

## Rounding and numeric precision

The SAS ROUND function rounds halves away from zero; Python round and numpy.round round halves to the
nearest even digit, and R round follows the same IEC 60559 rule. SAS stores numerics as 8-byte floats, but
a LENGTH shorter than 8 bytes truncates precision, and formats only change how values are displayed.
Rebuilds should compare unrounded scores.

## Logarithms and transformations

LOG(0) in SAS returns a missing value with a note in the log, while numpy returns minus infinity with a
warning and R returns -Inf. Derived variables such as log(credit_amount) need the same guard for zero or
negative inputs as the legacy code.

## Scoring output

PROC SCORE multiplies coefficients by variable values and returns linear combinations, so for a logistic
model it gives the linear predictor (log-odds), not a probability; the inverse logit must be applied
separately. In R, predict() on a glm returns the linear predictor by default (type = "link"); use
type = "response" for probabilities. statsmodels requires an explicit constant column (add_constant) when
the formula interface is not used.

## Quantiles, ranks and binning

PROC UNIVARIATE uses percentile definition 5 by default, while numpy and R use a linear interpolation rule
(type 7), so quantile-based bins can move a few records at the boundaries. PROC RANK and pandas rank both
average ties by default. Interval bins must use the same closed side as the legacy code (pandas.cut is
right-closed by default).

## Dates, strings and integers

SAS dates count days from 1 January 1960 and R Date values count from 1 January 1970. SAS character
comparisons ignore trailing blanks, Python string comparisons do not. The SAS INT function truncates toward
zero, while Python floor division rounds toward minus infinity for negative numbers.

## Gradient boosting versions

XGBoost results depend on the library version and parameters such as base_score, which recent versions
can estimate from the data when it is not set; pin the version and set base_score explicitly when
reproducing a legacy booster.
