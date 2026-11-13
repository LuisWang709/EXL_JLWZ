# A3 handoff: feat/a3-catchup

Historical handoff: A4 (LuisWang709), assisted by Claude, implemented the code-ready parts of A3's brief. A3's remaining work is review and decisions requiring human judgment. Declare that code/document drafts were AI-assisted and identify the actual review performed; a draft is not proof of review.

## 1. Implemented on this branch

| Brief item | Files | Result |
| --- | --- | --- |
| Validation library | validation/metrics.py | Eight functions, unchanged signatures; sklearn/scipy/hand-calculated reference tests |
| compute_metrics | MCP metrics.py | Registered datasets, applicable metrics, warnings for unsupported cases |
| RAG/search_kb | rag/store.py, kb | TF-IDF with optional FAISS/numpy fallback, no embedding API, rebuild on source changes |
| Template/rubric | model_doc.md.j2, rating/rubric.yaml | v1, tested against policy |
| Documentation | agents/doc/agent.py | Eight sections, E# evidence, unsupported LLM numbers/variables filtered |
| Rater | rating/rater.py, checks.py | Rules 60, separate LLM review 40, two vetoes; verify code/KB quotes |
| Calibration | test_rater.py, calibrate_rater.py | Mock: good 93/pass; five bad cases fail: missing sections/evidence, invented variable/number, generic filler |
| Documents API | routers/documents.py | Four endpoints; async draft/rate/revise, max three attempts |
| Reports | reporting/builder.py, templates | Analysis/validation, numeric source ledger, reject mismatched rendered numbers |
| Reports API | routers/reports.py | Type-filtered list/details/HTML |
| Fairness | fairness_m001.md, fairness_m001.py | Draft; 300-row fixture |
| Responsible AI | responsible_ai.md | Draft |
| Sign-off/Q&A | export_report_numbers.py, ss1_23_qa.md | Export works; questions remain review material |

CLI and MVP integration use real DocAgent/DocRater/ReportBuilderImpl. Recorded local Ruff/mypy/pytest/Bandit passed. This is a historical handoff, not current real-provider acceptance.

## 2. Try the branch

```bash
git fetch origin
git checkout feat/a3-catchup
uv sync --all-extras
uv run pytest -q
uv run python -m mrf.run --model tests/fixtures/classify/m001_pd_scorecard.sas --auto-approve
uv run python scripts/calibrate_rater.py --show-doc
uv run python scripts/build_kb.py "model documentation" --collection ss1_23
```

## 3. Human tasks, in order

1. **Review the PR.** A3/A4 own these paths; A4 authored the change, so A3 review is needed. Inspect document generation, rule scores, traffic lights, and SS1/23 summaries. Be able to explain them in Q&A.
2. **Add official SS1/23 source where permitted.** The current KB contains team summaries labeled not official text. Verify PRA source and reuse terms before committing. Example:
   ```bash
   uv run --with pypdf python scripts/import_kb_pdf.py <official-pdf> --collection ss1_23 --source "PRA SS1/23 - Model risk management principles for banks (official text)" --url https://www.bankofengland.co.uk/prudential-regulation/publication/2023/may/model-risk-management-principles-for-banks-ss --licence "<verified terms>"
   uv run python scripts/build_kb.py "documentation independent third party" --collection ss1_23
   ```
   If redistribution is not permitted, keep it local/deployment-only and document the arrangement.
3. **Align mapping notes with A2.** Merge or cross-reference kb/mapping/sas_r_python_differences.md with A2's specific mappings.
4. **Calibrate with the real demo provider.** CI is mock. Use the same Azure OpenAI deployment or approved OpenAI-compatible alternative, configured as in .env.example, and run calibrate_rater.py --show-doc. Optional MRF_LLM_REVIEWER_MODEL selects a separate reviewer model. Check good/bad document behavior and accuracy of added claims. Review SYSTEM_PROMPT values and rubric weights; AI can assist interpretation, but owners decide.
5. **Confirm thresholds with A1.** Proposed reporting values: Gini .40/.30; impact ratio .80/.70; HL p .05; age_band segmentation. These are team policy. Keep manual_baseline_hours empty until actual manual timing exists.
6. **Finalize fairness.** Run fairness_m001.py on full cleaned out-of-time data and corresponding scores, then rewrite interpretation, choose mitigation A-E, and complete the decision record. The fixture ratio is .69 with a red finding; younger groups also have higher bad rates and false rejection. This older handoff originally used under-30/45+ labels; current source/data bins are under-25/25-39/40+.
7. **Finalize Responsible AI.** Verify each statement against the deployed version and remove stale claims.
8. **Sign off numbers.** export_report_numbers.py --out signoff.csv exports report facts/sources. Use those facts for slides, checking each one. The historical handoff did not yet have MLflow connected; report facts remain the sign-off source.
9. **Prepare SS1/23 Q&A.** The original handoff had 15 draft questions; the current document contains 25. Check against official text and rehearse without reading.

## 4. Coordination

- A1: approve reporting thresholds and additive HTML/Markdown response declarations. MVP now asserts real A3 modules; MCP tests use a test-only fake rather than search_kb as an unimplemented example.
- A2: profiling populates document data facts. Put auc/gini/ks/brier/psi_score/hosmer_lemeshow in Run.metrics. Scoring outputs need a recognized score column and dataset row order for fairness joins.
- A4: ReportBuilderImpl delegates monitoring to MonitoringReportBuilder. UI can embed document/report HTML responses.

## 5. Design choices and limits

- Deterministic language-specific document statements focus on SAS link/event/CLASS/binning; R/Python receive fewer rule-derived statements.
- Numeric checks exempt integers <=10 to avoid false positives for enumerations/principle numbers.
- Default fairness threshold matches overall decline rate to observed bad rate; replace with the real business threshold when known.
- Numeric report mismatches prevent saving and escalate with MRF-5000.
- TF-IDF is deterministic/offline but weaker for paraphrased queries.
