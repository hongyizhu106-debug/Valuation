---
name: financial-model-review
description: Use this when reviewing valuation formulas, financial diagnostics, SEC data extraction, or charted financial metrics.
---

# Financial Model Review Skill

## Goal

Review whether a financial model, diagnostic metric, or chart calculation is source-traceable, formula-correct, and clearly separated from assumptions.

## Workflow

1. Identify the source data fields, periods, units, and concepts.
2. Identify assumptions separately from source facts.
3. Write the calculation formula in plain terms.
4. Check period alignment: fiscal year, quarter, TTM, or point-in-time balance sheet.
5. Check whether the result can be reconciled against a known source value or sample.
6. Flag missing data, low-confidence mappings, or market-data timing issues.

## Output

Return:

- metric or model reviewed,
- source fields inspected,
- formula,
- assumptions,
- verification performed,
- risks or data gaps.

## Rules

- Do not invent missing financial values.
- Do not treat market-implied results as accounting facts.
- Do not mix per-share, total company, and book-value metrics without explicit labels.
- Treat diagnostic output as analysis, not investment advice.
