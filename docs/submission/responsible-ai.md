# Responsible AI: Model Risk Factory

Review copy for Team A. This describes implementation controls, not an independent approval or compliance certificate.

## Purpose and accountability

The prototype identifies legacy models, drafts cited documentation, rebuilds scoring code and produces validation
and monitoring evidence. Human reviewers approve documentation at H1 and validation at H2. Audit events preserve
the actor and state transition. Evaluation scripts label their automated approvals as evaluation events.

## Evidence and privacy

Model documents cite parser output, source lines and knowledge-base chunks. The rater checks citations and can
veto fabricated variables or unsupported numbers. Reports render stored tool results and verify their numbers.
The profiling tool returns aggregates rather than raw rows. Source code, aggregate statistics and retrieved text
may reach the configured LLM provider. Data files and secrets stay outside git and container build contexts.

## Operational safeguards

Pattern guards screen common personal-data identifiers and prompt-injection phrases before prompting. Upload,
archive and step time limits constrain processing. A subprocess runs policy-checked scoring code. Cloud
environments reject missing agent implementations and forced stubs. These controls do not constitute a hardened
multi-tenant sandbox or a complete personal-data detector.

## Fairness and acceptance limits

Validation reports expose segment approval and error rates where appropriate data exists. Human owners decide
business thresholds and mitigations. Team traffic-light thresholds do not establish legal compliance. Current
SAS/R reference scores use Python reproduction, so independent exports from the legacy runtime are still needed.
The M003 Python source remains documentation-only without a trained scoring artefact and reference package.

## Evidence still required

Offline tests use a mock LLM. Real deployment calibration, representative data validation, measured manual effort
and independent review remain prerequisites for production or savings claims. The knowledge base is a team
paraphrase; the official SS1/23 index lists the April 2026 revision. A3 must verify regulatory interpretation and
the data owner must confirm provenance, permitted use and fairness conclusions before final submission.
