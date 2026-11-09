# Knowledge base sources (owner: A3)

```
kb/ss1_23/        PRA SS1/23 text, split by principle
kb/templates/     model documentation standard and exemplar docs
kb/mapping/       SAS/R <-> Python difference notes (reference coding, missing values, PROC defaults...)
kb/index/         reserved for a persisted index (git-ignored; the current index is built in memory)
```

`search_kb` (MCP tool, `src/mrf/mcp_server/tools/kb.py`) reads every `.md` / `.txt` file in the three
collection folders, splits it on headings, and ranks chunks with TF-IDF (FAISS when the `rag` extra is
installed, numpy otherwise). The index rebuilds automatically when a file changes - no build step.

Each source file starts with front-matter so `search_kb` can cite it:

```
---
source: PRA SS1/23 - Model risk management principles for banks
url: https://www.bankofengland.co.uk/prudential-regulation/publication/2023/may/model-risk-management-principles-for-banks-ss
licence: <what allows us to store it here>
---
```

Chunk ids are `<file stem>#<n>` and documents cite them as `kb:<chunk_id>`. Renaming or editing a file
changes its chunk ids, so regenerate documents after editing the KB.

## Current content

| File | What it is |
| --- | --- |
| `ss1_23/ss1_23_principles_summary.md` | Team paraphrase of the five principles plus how the project maps to them. **Not the official text** |
| `templates/model_documentation_standard.md` | The 8-section standard the documentation agent and rater use |
| `templates/exemplar_pd_scorecard_documentation.md` | Style exemplar for a fictional model (placeholders, no numbers) |
| `mapping/sas_r_python_differences.md` | Parity pitfalls; align with A2's mapping table |

## Adding the official SS1/23 text (A3)

1. Download the PDF from the PRA page above (or save the HTML version from the PRA Rulebook as text).
2. Check the licence / terms of use and decide whether the text may be committed to this repository.
3. Convert and add it:

   ```bash
   uv run --with pypdf python scripts/import_kb_pdf.py ~/Downloads/ss123.pdf --collection ss1_23 \
       --source "PRA SS1/23 - Model risk management principles for banks (official text)" \
       --url https://www.bankofengland.co.uk/prudential-regulation/publication/2023/may/model-risk-management-principles-for-banks-ss \
       --licence "<terms you checked>"
   uv run python scripts/build_kb.py "documentation independent third party" --collection ss1_23
   ```
