# Valuation

Valuation is a local Python project for financial statement research. It combines a lightweight SEC EDGAR filing reader with reusable valuation-method code for FCFE, FCFF, abnormal earnings, and abnormal NOPAT analysis.

The project is designed for analytical work, not investment advice. Source data, assumptions, calculations, and conclusions should stay clearly separated.

## What This Project Does

- Fetches public SEC filings by company name or ticker.
- Saves original filing HTML and metadata locally for repeatable research.
- Provides a browser-based local dashboard for searching and previewing filings.
- Implements compact valuation helpers for free cash flow and abnormal earnings methods.
- Keeps project guidance in `AGENTS.md` for financial statement diagnostic work.

## Repository Layout

```text
.
|-- app.py                              # Local filing search and preview dashboard
|-- scripts/
|   `-- fetch_sec_filings.py            # SEC EDGAR downloader
|-- valuation_methods/
|   |-- common.py                       # Shared present value helpers
|   |-- fcf.py                          # FCFE and FCFF valuation functions
|   |-- acf.py                          # Abnormal earnings / abnormal NOPAT functions
|   `-- __init__.py
|-- examples/
|   `-- valuation_methods_example.py    # Example valuation-method run
|-- docs/                               # Design notes and valuation method notes
|-- AGENTS.md                           # Project rules for financial diagnostics
`-- README.md
```

Local downloaded filings are written to `data/sec_filings/`. That folder is intentionally ignored by Git so the public repository stays focused on source code and documentation.

## Requirements

- Python 3.10 or newer
- No required third-party Python packages for the current core scripts
- Internet access when fetching SEC filings
- A descriptive SEC User-Agent string

SEC asks automated tools to identify themselves. Use your name and email, for example:

```powershell
$env:SEC_USER_AGENT="Your Name your.email@example.com"
```

## Quick Start

Clone the repository and enter the project folder:

```powershell
git clone <repository-url>
cd Valuation
```

Start the local dashboard:

```powershell
$env:SEC_USER_AGENT="Your Name your.email@example.com"
python app.py
```

Open the dashboard in a browser:

```text
http://127.0.0.1:8010
```

The dashboard lets you enter:

- company name or ticker,
- annual or quarterly report type,
- year and quarter filters,
- SEC User-Agent if it is not already set as an environment variable.

It downloads the matching SEC filing, stores it locally, and previews the original filing HTML.

## Fetch Filings From the Command Line

Fetch the latest annual and quarterly filing for Apple:

```powershell
python scripts/fetch_sec_filings.py Apple --user-agent "Your Name your.email@example.com"
```

Fetch only quarterly reports:

```powershell
python scripts/fetch_sec_filings.py Microsoft --forms 10-Q --user-agent "Your Name your.email@example.com"
```

Fetch the latest two annual and quarterly reports:

```powershell
python scripts/fetch_sec_filings.py NVDA --latest-per-form 2 --user-agent "Your Name your.email@example.com"
```

Files are saved under:

```text
data/sec_filings/<ticker>/<form>/<filing_date>_<accession_number>/
```

Example:

```text
data/sec_filings/AAPL/10-K/2025-10-31_0000320193-25-000079/
|-- aapl-20250927.htm
`-- metadata.json
```

An index is also written to:

```text
data/sec_filings/<ticker>/index.json
```

## Valuation Methods

The `valuation_methods` package contains small, explicit valuation helpers:

- `fcfe_valuation()`: discounts free cash flow to equity using the cost of equity and returns equity value.
- `fcff_valuation()`: discounts unlevered free cash flow using WACC, then bridges enterprise value to equity value.
- `abnormal_earnings_valuation()`: values equity as opening book value plus the present value of future abnormal earnings.
- `abnormal_nopat_valuation()`: values net operating assets as opening book value plus the present value of abnormal NOPAT, then bridges to equity value.

Run the example:

```powershell
python examples/valuation_methods_example.py
```

The valuation functions are intentionally transparent: inputs such as discount rates, terminal growth, book value, net debt, and non-operating assets must be provided explicitly. Historical filings can support assumptions, but they do not determine future growth, margins, reinvestment, leverage policy, or discount rates by themselves.

## Financial Diagnostic Principles

The broader model direction is documented in `AGENTS.md`. Diagnostic work should cover:

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

Reports should separate:

- source data,
- assumptions,
- calculations,
- conclusions,
- data gaps.

## Important Notes

- `10-K` is the annual report.
- `10-Q` is the quarterly report.
- Many companies do not have a separate Q4 `10-Q`; full-year results usually appear in the `10-K`.
- Quarter matching uses the SEC filing date quarter. The actual report period end date is still shown in dashboard results.
- Downloaded SEC filings are public source documents, but local cached copies are ignored by Git.
- The repository does not include private credentials, API keys, or generated local caches.

## Verification

Useful smoke checks:

```powershell
python examples/valuation_methods_example.py
python -m py_compile app.py scripts/fetch_sec_filings.py valuation_methods/*.py
```

When preparing financial analysis, also verify:

- source periods and units,
- formula consistency,
- key subtotals and totals where possible,
- net income versus operating cash flow,
- revenue growth versus receivables growth,
- debt trend versus interest coverage,
- missing inputs and confidence levels.

## Disclaimer

This project is for financial statement analysis and education. It does not provide investment advice, trading recommendations, or a guarantee of valuation accuracy.
