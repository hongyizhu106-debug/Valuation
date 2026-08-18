# Valuation

Valuation is a local Python research dashboard centered on abnormal earnings (AE), also known as residual income valuation. The project connects public SEC filing data with explicit AE assumptions so that users can separate source facts, model assumptions, valuation formulas, and conclusions.

This project is for research and education. It is not investment advice.

## Features

- Abnormal earnings / residual income valuation helpers with explicit capital-charge formulas.
- AE assumption review for cost of equity, book value of equity, forecast net income, persistence, terminal growth, buybacks, and dividends.
- SEC EDGAR filing lookup by company name or ticker.
- Local filing preview with search and zoom controls.
- Supporting net income, ROE, leverage, Altman score, and PE-premium diagnostics.
- Additional FCFE, FCFF, and abnormal NOPAT valuation helpers.
- Local-first data storage; downloaded SEC filings and caches are ignored by Git.

## Abnormal Earnings Model

The central equity model is:

```text
Equity value = Opening book value of equity + PV(future abnormal earnings)
Abnormal earnings = Net income - cost of equity * opening book value of equity
```

The dashboard and helper functions are designed to make the main assumptions visible instead of hiding them inside a black-box value:

- Source facts: reported net income, book value of equity, dividends, buybacks, filing periods, and market inputs when available.
- Cost of equity: the capital charge rate used both to calculate AE and discount future AE.
- Forecast path: future net income or future AE persistence, depending on the model path being tested.
- Persistence: the fade rate for excess profitability. In a direct AE-persistence model this is the AE persistence parameter; in a net-income-growth fade model `rho` controls how quickly growth moves toward terminal growth.
- Terminal value: the next-period abnormal earnings entry capitalized after the explicit forecast period.
- Capital return: buybacks and dividends reduce future book value of equity, which changes later capital charges and AE.

ROE and other diagnostics are supporting evidence. They help explain whether excess profitability looks durable, but they are not the center of the project.

## Public AE Example

Run a small public example with deliberately simple numbers:

```powershell
python examples/abnormal_earnings_example.py
```

Example output:

```json
{
  "model": "abnormal earnings / residual income",
  "formula": "Equity value = opening BVE + PV(future AE); AE = NI - cost_of_equity * opening BVE",
  "assumptions": {
    "opening_book_value_equity": 900,
    "cost_of_equity": 0.1,
    "terminal_growth": 0.02,
    "shares_outstanding": 100
  },
  "explicit_abnormal_earnings": [
    {
      "year": 1,
      "abnormal_earnings": 30.0,
      "present_value": 27.27
    },
    {
      "year": 2,
      "abnormal_earnings": 37.0,
      "present_value": 30.58
    },
    {
      "year": 3,
      "abnormal_earnings": 43.0,
      "present_value": 32.31
    }
  ],
  "terminal_present_value": 411.91,
  "equity_value": 1402.07,
  "value_per_share": 14.02
}
```

The example is not a company recommendation. It exists to show the mechanics: opening BVE of 900, explicit AE present value of 90.16, terminal AE present value of 411.91, and total equity value of 1,402.07.

## Quick Start

```powershell
git clone https://github.com/hongyizhu106-debug/Valuation.git
cd Valuation
$env:SEC_USER_AGENT="Your Name your.email@example.com"
python start_dashboard.py
```

Open:

```text
http://127.0.0.1:8010
```

SEC requests should include a descriptive User-Agent. You can pass it in the dashboard form or set `SEC_USER_AGENT`.

## Command Line Filing Download

```powershell
python scripts/fetch_sec_filings.py Apple --user-agent "Your Name your.email@example.com"
python scripts/fetch_sec_filings.py Microsoft --forms 10-Q --user-agent "Your Name your.email@example.com"
python scripts/fetch_sec_filings.py NVDA --latest-per-form 2 --user-agent "Your Name your.email@example.com"
```

Downloaded filings are saved under:

```text
data/sec_filings/<ticker>/<form>/<filing_date>_<accession_number>/
```

That directory is intentionally excluded from the public repository.

## Project Layout

```text
.
|-- app.py                         # local dashboard and financial diagnostics
|-- start_dashboard.py             # dashboard launcher
|-- scripts/                       # SEC downloader and research utilities
|-- valuation_methods/             # valuation calculation helpers
|-- examples/                      # runnable examples
|-- .github/                       # CI and PR governance
|-- .agents/                       # reusable agent workflows
|-- pyproject.toml                 # package metadata
|-- AGENTS.md                      # durable agent instructions
`-- README.md
```

Internal notes, local reference documents, downloaded filings, cache files, and local packaging artifacts are intentionally excluded from the public package.

## Valuation Helpers

The `valuation_methods` package exposes:

- `abnormal_earnings_valuation()`
- `fcfe_valuation()`
- `fcff_valuation()`
- `abnormal_nopat_valuation()`

Run the example:

```powershell
python examples/abnormal_earnings_example.py
python examples/valuation_methods_example.py
```

The helpers require explicit inputs for discount rates, book values, terminal growth, net debt, non-operating assets, and shares outstanding. Historical filings support assumption review, but the code does not invent future assumptions.

## Verification

```powershell
python -m compileall -q app.py start_dashboard.py scripts valuation_methods examples
python examples/abnormal_earnings_example.py
python examples/valuation_methods_example.py
```

CI runs the same smoke checks on pull requests and pushes to `main`.

## Data and Risk Boundaries

- Source data, assumptions, calculations, and conclusions should remain separate.
- Missing data should be flagged instead of filled with guessed values.
- Current market and company data can change; refresh source data before relying on a result.
- Diagnostic output is analytical only and should not be treated as a trading recommendation.

## License

This project is released under the MIT License.
