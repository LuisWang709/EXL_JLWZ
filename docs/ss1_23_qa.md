# SS1/23 and model-risk Q&A bank (DRAFT for A3)

> Draft answers for judges' questions. A3 must check every SS1/23 statement against the official text (once it is
> in `kb/ss1_23/`) and be able to give each answer without notes. Numbers: quote them only from the reports /
> `scripts/export_report_numbers.py`.

## About SS1/23

**Q1. What is SS1/23 and who does it apply to?**
The PRA supervisory statement on model risk management for banks, originally published 17 May 2023 with PS6/23.
The official landing page lists the April 2026 revision as the current version (published/effective 23 April 2026).
It is aimed at UK banks, building societies and PRA-designated investment firms with internal model
approval for regulatory capital; the PRA encourages other firms to use it proportionately.
See [the current-version index](https://www.bankofengland.co.uk/prudential-regulation/publication/2023/may/model-risk-management-principles-for-banks-ss).

**Q2. What are the five principles?**
(1) model identification and model risk classification, (2) governance, (3) model development, implementation and
use, (4) independent model validation, (5) model risk mitigants.

**Q3. Which parts of SS1/23 does your system address?**
Principle 1: the identification agent classifies each model and records it in the inventory with a confidence.
Principle 3: documentation with evidence for every statement, the Python rebuild with a parity test as
implementation testing. Principle 4: the validation report and post-deployment monitoring (PSI/CSI, Gini drop,
alerts, re-validation). Principles 2 and 5: mandatory human gates H1/H2, manual review queue, audit trail.
We do not replace model tiering or board reporting - those stay with the bank.

**Q4. What does SS1/23 expect from model documentation?**
Enough detail for an independent, knowledgeable third party to understand how the model works, its assumptions,
limitations and data, and the conditions under which it should not be used - in principle enough to replicate
it. Our eight sections follow that expectation (`kb/templates/model_documentation_standard.md`).

## About our approach

**Q5. How do you stop the LLM from inventing facts?**
Facts come only from MCP tools (code parser, inventory, data profile, metrics, knowledge base). Every statement
must cite evidence; statements with unknown evidence, untraceable numbers or invented variables are dropped by the
writer and vetoed by the rater; code and knowledge-base quotes are verified against their source; report numbers
are rendered from stored results and re-checked after rendering.

**Q6. The same kind of model writes and grades the documentation - isn't that circular?**
60 of 100 points are deterministic checks the LLM cannot influence (section completeness, evidence coverage,
variables vs the rater's own parse of the code) plus two vetoes. The LLM reviewer uses a separate prompt and
context, can run on a different model and adds at most 40 points. We calibrated it with deliberately broken
documents (`scripts/calibrate_rater.py`): all of them fail.

**Q7. Why a Python rebuild, and how do you know it is right?**
Legacy SAS/R code is hard to validate and run; the rebuild makes the model testable and portable. Parity compares
legacy and rebuilt scores record by record against an absolute tolerance in `config/pipeline.yaml`; the rebuild
agent gets the mismatch details and our SAS/R-to-Python notes (outcome ordering, reference coding, missing values,
rounding) on each retry, and escalates to a human after the configured number of attempts.

**Q8. What do the traffic lights in the analysis report mean?**
Consistency: parity passed or not. Performance: Gini against the green/amber thresholds, downgraded by a failing
Hosmer-Lemeshow test. Stability: score PSI against the monitoring thresholds. Fairness: disparate impact across
segments against the four-fifths rule. Thresholds are team policy in `config/pipeline.yaml`, not regulation.

**Q9. Why PSI, and why those thresholds?**
PSI compares the distribution of a variable between the development sample and a new batch; it is the industry
standard for population drift. The common rule of thumb is below 0.10 stable, 0.10-0.25 moderate shift, above 0.25
significant shift - we use exactly those values for green / amber / red.

**Q10. What about fairness?**
We measure approval rates, adverse impact ratio, TPR and FPR by segment. For M001 the under-25 band fails the
four-fifths rule on the sample, partly because its observed bad rate is higher; the stronger concern is that good
payers under 30 are declined more often. Options and the decision are in `docs/fairness_m001.md`.

**Q11. Can the system approve a model on its own?**
No. H1 (documentation) and H2 (validation sign-off) are mandatory human decisions; failures and low confidence go
to a manual review queue; every state change is audited with its actor.

**Q12. What happens after deployment?**
Each new batch gets data-quality checks and PSI/CSI against the baseline; amber and red raise alerts, and red
sends the model back to the usability run and a new H2 sign-off.

**Q13. Why TF-IDF retrieval rather than embeddings?**
The knowledge base is small and terminology-heavy; TF-IDF is deterministic, needs no embedding service, runs
offline in CI and in the container, and every hit carries its source and line range.
FAISS accelerates the same local ranking when installed; numpy remains the supported container backend.
An Azure AI Search backend is an optional extension and has not been implemented.

**Q14. How would this scale to 250 models?**
The pipeline is per model and asynchronous; cost and time per model are tracked in the pipeline usage and shown
in the analysis report. The business case multiplies measured per-model figures - no estimates are used.

**Q15. What are the main limitations?**
See `docs/responsible_ai.md`: the knowledge base paraphrases the official source, pattern guards have blind spots,
and fairness numbers use a small fixture. Team thresholds are not regulatory limits. Real LLM calibration,
independent legacy-runtime output and measured manual effort remain acceptance dependencies.

**Q16. Does a passing parity test prove that the original model is correct?**
It proves agreement with the supplied reference scores on the tested inputs and tolerance. It does not establish
conceptual soundness or validity outside those inputs. Current SAS/R reference scores were reproduced in Python,
so independent SAS/R exports remain an important data-team acceptance item.

**Q17. Can a model reach monitoring without a dataset?**
Yes, for documentation demonstrations. The orchestrator records that scoring was skipped. The evaluation harness
marks this run as incomplete for reporting, and validation dimensions without observations remain unassessed.

**Q18. What happens if a deployed module is missing?**
dev/demo reject forced stubs and missing implementations. Readiness reports an agent-load failure instead of
silently replacing a module with simulated behaviour.

**Q19. What do the LLM cost figures measure?**
Token usage multiplied by configured model prices. They are estimates, not provider invoices, and mock usage is
not a claim about production latency or expense. Compare deployment runs and the actual invoice before budgeting.

**Q20. How do you test the self-correction loop?**
Unit tests return a deliberately wrong reference-level translation, check the parity diagnosis, then provide a
corrected translation. A mock demo can enable the same story, but it must be labelled as simulated.

**Q21. Can the system execute arbitrary uploaded Python?**
Generated scoring code is checked against the restricted scoring contract before a subprocess executes it.
This is a demo control, not a hardened multi-tenant execution environment. Hostile workloads need stronger isolation.

**Q22. Who may sign off a fairness finding?**
The responsible human reviewer records the decision and its conditions at H2. The system surfaces the metrics
and limitations but cannot certify legal compliance or choose a business cut-off on behalf of the owner.

**Q23. What has the team measured about business savings?**
No manual baseline has been supplied. The report omits savings until measured manual hours and an agreed cost
rate are available. Multiplying an unmeasured assumption across a portfolio would not be an observed result.

**Q24. How are cloud artefacts kept private?**
Azure Files remains the deployment default. The optional Azure Blob adapter uses managed identity and accepts
only its configured account/container URLs. Neither adapter makes reports public automatically.

**Q25. What must happen before a final submission?**
Complete the data handoff and independent reference runs, calibrate the deployed LLM, obtain owner approvals,
check deployment and CI, record/publish the demo, and have the team send and archive the submission email.
