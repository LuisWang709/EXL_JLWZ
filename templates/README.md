# templates

| Template | Owner | Rendered by |
| --- | --- | --- |
| `model_doc.md.j2` | A3 | `mrf.agents.doc.agent.DocAgent` - section ids must match `src/mrf/rating/rubric.yaml` |
| `analysis_report.html.j2` | A3 | `mrf.reporting.builder.ReportBuilderImpl` (usability RAG + process improvement) |
| `validation_report.html.j2` | A3 | same - the H2 sign-off pack |
| `_report_base.html.j2`, `_report_macros.html.j2` | A3 | shared layout / tables for the two reports |
| `parity_certificate.html.j2` | A2 | (to come) |
| `monitoring_report.html.j2` | A4 | (to come; `ReportBuilderImpl` delegates `monitoring` to `mrf.monitoring.report`) |

Report templates never print a raw number: use `num("<fact key>", "<format spec>")` so the number is recorded with
its source and re-checked after rendering (`mrf.reporting.numbers`). Put labels, ids and dates inside
`<span class="meta">`. A number typed directly into a template makes the report fail its number check.
