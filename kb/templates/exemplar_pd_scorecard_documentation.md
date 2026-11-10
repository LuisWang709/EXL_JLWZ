---
source: Exemplar model documentation for a fictional PD scorecard (team-written; placeholders instead of numbers)
url: kb/templates/model_documentation_standard.md
licence: Team-written for the EXL x UCD hackathon
---

# Exemplar - fictional retail PD scorecard EX-01

This exemplar shows the expected style. It describes a fictional model; every value in angle brackets is a
placeholder that the documentation agent must replace with a value from a tool output, or drop. Never copy
the wording of a placeholder into a real document.

## Exemplar purpose and use

- EX-01 estimates the 12-month probability of default of new retail loan applicants and supports the
  approve / decline decision at application. [E1]
- The model is owned by Retail Credit Risk and is not intended for behavioural scoring of existing
  customers or for pricing. [E2]

## Exemplar data

- The development sample is the cleaned application dataset with <row_count from profile_data> rows;
  the target `default_flag` equals 1 for a bad outcome. [E3][E4]
- | Variable | Type | Role | Reference level | Evidence |
  | `checking_status` | categorical | feature | <reference level from parse_code> | [E5] |

## Exemplar methodology

- Logistic regression with a logit link estimated with a maximum-likelihood procedure; the event modelled
  is `default_flag` = 1. [E5]
- Categorical variables use reference coding, so each coefficient is the log-odds difference against the
  stated reference level. [E5][E6]

## Exemplar assumptions and limitations

- The relationship between the drivers and default is assumed to be stable between the development window
  and the scoring population; drift is monitored with PSI/CSI. [E7]
- The legacy code derives an age band from age with fixed cut-offs; applicants close to a cut-off move band
  with a small change in age. [E5]

## Exemplar performance

- Out-of-time Gini is <gini from compute_metrics> and KS is <ks from compute_metrics>. [E8]

## Exemplar implementation

- The SAS model is rebuilt in Python and reconciled record by record with the legacy scores within the
  parity tolerance from the pipeline configuration. [E9][E10]

## Exemplar monitoring

- Monthly batches are compared with the development baseline; PSI above the amber threshold raises an amber
  alert and above the red threshold triggers re-validation. [E11]

## Exemplar governance

- Documentation approval (H1) and validation sign-off (H2) are mandatory human gates; failures after the
  maximum number of retries go to the manual review queue. [E12]
