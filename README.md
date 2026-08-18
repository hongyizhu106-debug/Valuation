# Valuation

Valuation is a local Python dashboard for SEC financial-statement research and transparent valuation diagnostics. It fetches public SEC filings, extracts comparable financial metrics, and provides reusable FCFE, FCFF, abnormal earnings, and abnormal NOPAT valuation helpers.

This project is for research and education. It is not investment advice.

## Features

- SEC EDGAR filing lookup by company name or ticker.
- Local filing preview with search and zoom controls.
- Net income, ROE, leverage, Altman score, and PE-premium growth diagnostics.
- Explicit valuation helpers for FCFE, FCFF, abnormal earnings, and abnormal NOPAT.
- Local-first data storage; downloaded SEC filings and caches are ignored by Git.

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

- `fcfe_valuation()`
- `fcff_valuation()`
- `abnormal_earnings_valuation()`
- `abnormal_nopat_valuation()`

Run the example:

```powershell
python examples/valuation_methods_example.py
```

The helpers require explicit inputs for discount rates, book values, terminal growth, net debt, non-operating assets, and shares outstanding. Historical filings support assumption review, but the code does not invent future assumptions.

## Verification

```powershell
python -m compileall -q app.py start_dashboard.py scripts valuation_methods examples
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
