# AGENTS.md

This repository is for building and refining a financial statement health diagnostic model.

## Project purpose

The core objective is to evaluate the financial health of a company using its financial statements and related disclosures.

The model should help diagnose:

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
- financial statement red flags,
- overall financial health.

## Critical rules

- Do not invent financial data, market data, company metrics, dates, filings, or management commentary.
- Keep source data, assumptions, calculations, and conclusions clearly separated.
- If data is missing, flag the gap instead of guessing.
- Preserve original source files unless the user explicitly asks to edit them.
- Create new output files for revised models, summaries, or reports unless instructed otherwise.
- For current company, market, regulatory, or macro information, verify with current sources before relying on it.
- Do not present diagnostic output as investment advice. Frame conclusions as analytical observations based on available data.

## Financial statement diagnostic framework

When building or reviewing the diagnostic model, organize analysis into these dimensions:

### 1. Profitability

Assess:

- gross margin,
- operating margin,
- net margin,
- return on assets,
- return on equity,
- return on invested capital where data allows.

Flag:

- declining margins,
- profits driven by one-off gains,
- ROE inflated mainly by leverage,
- large gap between operating profit and net profit without clear explanation.

### 2. Revenue quality

Assess:

- revenue growth,
- growth consistency,
- customer or product concentration if disclosed,
- organic versus acquisition-driven growth if identifiable.

Flag:

- revenue growth without matching cash collection,
- sharp growth slowdown,
- unusually high receivables growth versus revenue growth.

### 3. Cash flow quality

Assess:

- operating cash flow,
- free cash flow,
- cash conversion,
- operating cash flow versus net income,
- capital expenditure intensity.

Flag:

- persistent positive earnings with weak operating cash flow,
- free cash flow deterioration,
- large working capital outflows,
- aggressive capitalization of costs.

### 4. Balance sheet strength

Assess:

- cash and equivalents,
- total debt,
- net debt,
- equity base,
- intangible asset exposure,
- retained earnings trend where available.

Flag:

- rising debt with weakening cash flow,
- negative equity,
- large goodwill or intangibles relative to equity,
- frequent asset impairments.

### 5. Liquidity

Assess:

- current ratio,
- quick ratio,
- cash ratio,
- short-term debt coverage,
- operating cash flow coverage.

Flag:

- short-term liabilities exceeding liquid assets without stable cash generation,
- working capital stress,
- refinancing dependency.

### 6. Solvency and leverage

Assess:

- debt-to-equity,
- debt-to-assets,
- net debt / EBITDA where data allows,
- interest coverage,
- debt maturity risk where disclosed.

Flag:

- rising leverage with falling interest coverage,
- covenant or refinancing risk,
- debt-funded dividends or buybacks.

### 7. Working capital

Assess:

- days sales outstanding,
- days inventory outstanding,
- days payable outstanding,
- cash conversion cycle,
- receivables growth versus revenue growth,
- inventory growth versus cost of goods sold.

Flag:

- receivables growing faster than revenue,
- inventory growing faster than sales,
- payables stretched unusually high,
- cash conversion cycle deterioration.

### 8. Accounting quality and red flags

Assess:

- accruals,
- unusual one-off items,
- related-party transactions,
- restatements,
- auditor concerns,
- non-GAAP adjustments,
- changes in accounting policy.

Flag:

- repeated adjusted earnings exclusions,
- unexplained margin expansion,
- large non-cash gains,
- frequent restructuring charges,
- mismatch between narrative and financials.

## Model output structure

When creating a diagnostic report, use this structure:

1. Executive summary
2. Overall health score
3. Dimension scores
4. Key strengths
5. Key weaknesses
6. Red flags
7. Data gaps
8. Assumptions
9. Calculation appendix

## Scoring guidance

Use a transparent scoring system.

Recommended default:

- 0-20: severe financial stress
- 21-40: weak financial health
- 41-60: mixed / watchlist
- 61-80: healthy
- 81-100: very strong

Each dimension should include:

- score,
- rationale,
- supporting metrics,
- trend direction,
- confidence level.

Do not use false precision. If the data is incomplete, lower confidence rather than forcing a precise score.

## Calculation standards

- Show formulas for every derived metric.
- Keep units clear: currency, percentage, multiple, days, or ratio.
- State whether figures are annual, quarterly, trailing twelve months, or point-in-time balance sheet values.
- Cross-check totals, subtotals, and period labels.
- Do not mix fiscal years, calendar years, and trailing periods without clearly labeling them.
- If currency differs across sources, do not combine figures until currency treatment is clear.

## File handling

- Keep source financial statements unchanged.
- Put derived models, diagnostics, and reports in clearly named files.
- Use descriptive filenames such as:
  - `company_name_financial_health_diagnostic_YYYY-MM-DD.xlsx`
  - `company_name_financial_health_report_YYYY-MM-DD.md`
  - `company_name_ratio_analysis_YYYY-MM-DD.csv`

## Verification

Before finalizing financial analysis:

- confirm source periods and units,
- check formulas,
- reconcile key totals where possible,
- compare net income with operating cash flow,
- compare revenue growth with receivables growth,
- compare debt trend with interest coverage,
- identify missing or low-confidence inputs.

If verification cannot be completed, explain exactly what is missing.

## Final response format

When completing a task in this repository, summarize:

- what was created or changed,
- source files used,
- key assumptions,
- key findings,
- verification performed,
- unresolved data gaps or risks.

