---
source: PRA SS1/23 Model risk management principles for banks - team summary (paraphrase, not the official text)
url: https://www.bankofengland.co.uk/prudential-regulation/publication/2023/may/model-risk-management-principles-for-banks-ss
licence: Team-written paraphrase for the EXL x UCD hackathon. Verify against the official text before quoting it.
---

# SS1/23 at a glance

Version note checked 12 November 2026: the official index lists the April 2026 revision as current,
published and effective 23 April 2026. The paragraphs below remain the team's earlier paraphrase and need
owner review against that revision. The original dates below describe the first publication only.
Current PDF: https://www.bankofengland.co.uk/-/media/boe/files/prudential-regulation/supervisory-statement/2026/liaf0126app5.pdf

The PRA supervisory statement SS1/23 sets out what the PRA expects from banks when they manage model risk.
It was published on 17 May 2023 together with policy statement PS6/23 and took effect on 17 May 2024.
The statement asks firms to treat model risk as a risk discipline in its own right and to manage it
strategically across the whole model lifecycle. Its primary audience is UK banks, building societies and
PRA-designated investment firms that hold internal model approval for regulatory capital; other firms are
encouraged to use the principles in a proportionate way.

The expectations are organised as five principles: (1) model identification and model risk
classification, (2) governance, (3) model development, implementation and use, (4) independent model
validation and (5) model risk mitigants.

## What counts as a model and what model risk is

A model is a quantitative method that applies statistical, economic, financial or mathematical theory and
assumptions to turn input data into quantitative estimates. Model risk is the potential for adverse
consequences (financial loss, poor decisions, reputational damage) when decisions rely on model outputs
that are wrong, or when a model is used outside the purpose and conditions it was designed for. Model risk
can be reduced through good model risk management but never removed completely, so it has to be
identified, measured, monitored and reported like other risks.

# Principle 1 - Model identification and model risk classification

Firms should apply a clear definition of a model so that the scope of the model risk management framework
is unambiguous. They should keep a complete model inventory that records, for every model, its purpose and
intended use, owner, developer, users, validation status, known limitations, any restrictions on use and
its interdependencies with other models and data. Each model should be classified (tiered) by model risk,
taking into account how material its use is and how complex or uncertain the method is. The tier drives how
much scrutiny the model receives: depth of validation, documentation, frequency of review and approval
authority.

# Principle 2 - Governance

The board is responsible for the model risk management framework and for setting the firm's appetite for
model risk; it should receive regular reporting on model risk and challenge it. A senior manager under the
Senior Managers Regime should be accountable for the framework, its policies and its implementation.
Policies and procedures should cover the full model lifecycle - development, implementation, use,
validation, monitoring, change and retirement - and define clear roles and responsibilities for model
owners, developers, users and validators. Internal audit should periodically assess whether the framework
is effective. Models bought from vendors or developed by third parties are in scope and should meet the
same standards, with the firm understanding them well enough to manage their risk.

# Principle 3 - Model development, implementation and use

## Purpose, design and data

Each model should have a clearly stated purpose and intended use, and its design and methodology should be
fit for that purpose and supported by theory or evidence. Data used to develop the model should be relevant,
representative of the population the model will be applied to, of adequate quality, and its limitations and
any adjustments to it should be documented.

## Development testing, judgement and adjustments

Developers should test the model before it is used: performance (discrimination and calibration for credit
models), stability, sensitivity to key assumptions and inputs, and comparison with benchmarks or
alternative approaches. Expert judgement and adjustments made during development should be justified,
documented and subject to challenge.

## Documentation

Model documentation should be detailed enough for an independent, knowledgeable third party to understand
how the model works, its key assumptions and limitations, the data it uses and the conditions under which it
should not be used, and in principle to replicate the model. Documentation should be kept up to date when the
model changes.

## Implementation and use

Before a model goes live, its implementation should be tested to show that the production code and systems
produce the outputs the approved design intends (for example by reconciling outputs between environments).
Models should only be used within their intended scope; users should understand the limitations, and model
owners should monitor performance on an ongoing basis.

# Principle 4 - Independent model validation

Models should be validated by people who are independent of model development and have the expertise and
authority to challenge it. Validation should assess conceptual soundness, data, implementation (process
verification), and outcomes - for example back-testing and benchmarking. Validation findings should be
recorded, rated, tracked and remediated, and the validation result should feed the decision to approve a
model for use.

## Ongoing performance monitoring and periodic revalidation

After approval, model performance should be monitored against defined thresholds (for example population
stability, discrimination and calibration), with breaches escalated and acted on. Models should be
revalidated periodically, at a frequency that reflects their tier, and whenever a material change or a
performance deterioration is identified.

# Principle 5 - Model risk mitigants

Firms should have processes to mitigate model risk when weaknesses are known: post-model adjustments with
appropriate governance and justification, restrictions on the use of a model until issues are fixed, and a
process for exceptions (for example using a model that has not been validated) that is time-limited,
approved at the right level and escalated. Model risk, including outstanding issues and adjustments, should
be reported to senior management and the board.

# How this project maps to SS1/23

- Principle 1: the identification agent classifies each uploaded legacy model (language, algorithm, purpose,
  target, features) and records it in the model inventory with a confidence score; low confidence goes to
  manual review instead of being accepted silently.
- Principle 2: human gates are part of the pipeline - documentation approval (H1) and validation sign-off
  (H2) - and every state change is written to an audit log with the actor.
- Principle 3: the documentation agent writes SS1/23-aligned documentation in which every claim cites its
  evidence (code line, data profile, tool output or knowledge-base chunk), and an independent rater scores it
  before H1. The rebuild agent re-implements the model in Python and a parity test reconciles its scores
  with the legacy model record by record (implementation testing).
- Principle 4: the validation report computes discrimination, calibration, stability and fairness metrics
  from tool outputs and is signed off by a human at H2; monitoring tracks PSI/CSI and Gini on new batches
  and raises amber/red alerts.
- Principle 5: when retries are exhausted or a check fails, the pipeline routes the model to a manual review
  queue instead of proceeding, and red drift triggers re-validation.
