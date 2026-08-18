# AGENTS.md

This file defines durable instructions for coding agents working in this repository.

## Project Mission

Valuation is a local Python dashboard and utility package for SEC financial-statement research, valuation helpers, and financial health diagnostics.

Primary quality goals:

- correctness of financial calculations,
- source-data traceability,
- maintainable local Python code,
- clear separation of facts, assumptions, calculations, and conclusions.

## Architecture Overview

- `app.py` owns the local HTTP dashboard, SEC/Yahoo data integration, chart rendering, and diagnostic table assembly.
- `start_dashboard.py` starts the dashboard and opens the browser.
- `scripts/` contains command-line utilities and research scripts.
- `valuation_methods/` contains reusable valuation formulas.
- `examples/` contains runnable examples and smoke checks.
- `.github/` contains CI and pull-request governance.
- `.agents/` contains reusable agent workflows.

## Critical Rules

- Do not invent financial data, market data, company metrics, dates, filings, or management commentary.
- Keep source data, assumptions, calculations, and conclusions clearly separated.
- If data is missing, flag the gap instead of guessing.
- Preserve original source filings and downloaded data; do not edit files under `data/sec_filings/`.
- Do not present diagnostic output as investment advice.
- For current market, company, regulatory, or macro facts, verify with current sources before relying on them.
- Do not add production dependencies without explicit user approval.
- Do not commit local caches, downloaded filings, course PDFs, zip packages, or internal reference notes.

## Implementation Rules

- Inspect relevant files before editing.
- Make the smallest change that satisfies the request.
- Preserve unrelated user changes.
- Follow existing local patterns unless a narrow refactor is required.
- Keep numerical formulas explicit and readable.
- For financial or numerical logic changes, include formula notes and before/after verification where practical.
- Update `README.md` when public setup, behavior, or repository structure changes.

## Financial Diagnostic Scope

Diagnostics may cover:

- profitability quality,
- revenue growth and durability,
- margin structure,
- cash flow quality,
- balance sheet strength,
- leverage and solvency,
- liquidity,
- working capital pressure,
- capital allocation,
- accounting quality,
- financial statement red flags.

## Calculation Standards

- Show formulas for every derived metric in user-facing explanations or chart notes.
- Keep units clear: currency, percentage, multiple, days, or ratio.
- State whether figures are annual, quarterly, trailing twelve months, or point-in-time balance sheet values.
- Do not mix fiscal years, calendar years, and trailing periods without clear labels.
- Cross-check totals, subtotals, and period labels where possible.
- If currency differs across sources, do not combine figures until currency treatment is clear.

## Verification

Run the narrowest relevant checks before finishing:

```powershell
python -m compileall -q app.py start_dashboard.py scripts valuation_methods examples
python examples/valuation_methods_example.py
```

For dashboard/API behavior changes, also start the local server and call the relevant endpoint when practical.

If a check cannot be run, report:

1. the exact command,
2. why it was not run,
3. what risk remains.

## Git and Release Rules

- Stage only files related to the task.
- Never force-push unless the user explicitly asks.
- Keep the public repository root clean.
- Public package should include source, examples, CI, README, and agent rules.
- Public package should exclude internal references, local notes, downloaded source data, caches, binaries, and zip artifacts.

## Completion Checklist

Before the final response, confirm:

- changed only files relevant to the request,
- preserved public behavior unless requested,
- ran relevant checks or explained why not,
- listed known risks or follow-ups,
- separated source files, assumptions, calculations, and verification in the summary.
