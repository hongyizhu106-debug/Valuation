"""Compare PE-AE and direct PE-premium one-year NI forecasts.

This is a read-only research script. It uses the dashboard's existing SEC/Yahoo
helpers and does not modify source data.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app  # noqa: E402


USER_AGENT = "Valuation Dashboard local-research@example.com"


def annual_filing(submissions, company, year: int):
    filings, _ = app.find_same_type_filings_for_vertical_compare(
        submissions,
        company,
        USER_AGENT,
        "10-K",
        year,
        None,
        lookback_years=0,
    )
    return filings[0] if filings else None


def load_backtest_inputs(company, submissions, facts, base_year: int) -> dict:
    filing = annual_filing(submissions, company, base_year)
    next_filing = annual_filing(submissions, company, base_year + 1)
    if filing is None or next_filing is None:
        raise RuntimeError(f"Missing 10-K for {base_year} or {base_year + 1}.")

    comparison_filings, _ = app.find_same_type_filings_for_vertical_compare(
        submissions,
        company,
        USER_AGENT,
        "10-K",
        base_year,
        None,
        lookback_years=4,
    )
    comparison_filings = sorted(
        [item for item in comparison_filings if int(item.report_date[:4]) <= base_year],
        key=lambda item: item.report_date,
    )

    continuous_filings, _ = app.find_continuous_quarter_filings_for_vertical_compare(
        submissions,
        company,
        USER_AGENT,
        filing,
    )
    monthly_pe_rows = app.build_monthly_pe_rows(facts, company.ticker, continuous_filings or [filing])
    pe = app.latest_market_pe(monthly_pe_rows)
    if pe is None:
        raise RuntimeError(f"Missing PE for {company.ticker} {base_year}.")

    ni0, _ = app.extract_ttm_value(facts, filing, ["NetIncomeLoss"])
    actual_next_ni, _ = app.extract_ttm_value(facts, next_filing, ["NetIncomeLoss"])
    if ni0 is None or actual_next_ni is None:
        raise RuntimeError(f"Missing NetIncomeLoss for {company.ticker} {base_year}.")

    equity_entry = app.extract_equity_entry(facts, filing)
    bve0 = equity_entry["raw_value"] if equity_entry else None
    if not isinstance(bve0, (int, float)) or bve0 <= 0:
        raise RuntimeError(f"Missing positive BVE for {company.ticker} {base_year}.")

    buybacks = app.historical_ttm_capital_returns(
        facts,
        comparison_filings,
        ["PaymentsForRepurchaseOfCommonStock", "StockRepurchasedAndRetiredDuringPeriodValue"],
    )
    dividends = app.historical_ttm_capital_returns(
        facts,
        comparison_filings,
        ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock", "Dividends"],
    )
    if not buybacks or not dividends:
        raise RuntimeError(f"Missing buyback/dividend history for {company.ticker} {base_year}.")

    decomposition_rows = app.build_historical_ni_decomposition_rows(
        facts,
        comparison_filings,
        max_report_date=app.parse_iso_date(filing.report_date),
    )
    rho, _, _ = app.estimate_ni_fade_rho(decomposition_rows, app.CURRENT_INFLATION_RATE)

    return {
        "pe": float(pe),
        "ni0": float(ni0),
        "actual_next_ni": float(actual_next_ni),
        "bve0": float(bve0),
        "buyback_base": sum(float(row["value"]) for row in buybacks) / len(buybacks),
        "dividend_ttm": float(dividends[-1]["value"]),
        "dividend_growth": app.average_growth_rate(dividends),
        "rho": float(rho),
    }


def pe_implied_next_ni(inputs: dict) -> float:
    """Old method: solve market value = BVE + PV(AE), then take Year-1 NI."""
    _, path, _ = app.solve_implied_roe_spread_model(
        inputs["pe"] * inputs["ni0"],
        inputs["ni0"],
        inputs["bve0"],
        inputs["buyback_base"],
        inputs["dividend_ttm"],
        app.DEFAULT_EQUITY_COST,
        app.CURRENT_INFLATION_RATE,
        app.CURRENT_INFLATION_RATE,
        inputs["dividend_growth"],
        inputs["rho"],
        app.IMPLIED_NI_FORECAST_YEARS,
        app.LINEAR_NI_GROWTH_EXTENSION_YEARS,
    )
    if not path:
        raise RuntimeError("PE-implied solver did not converge.")
    return float(path[0]["net_income"])


def pe_premium_next_ni(inputs: dict) -> float:
    """Direct PE method: premium = PE - 15, g1 = premium / 100."""
    _, _, path = app.build_pe_premium_ni_growth_path(
        net_income_ttm=inputs["ni0"],
        pe=inputs["pe"],
        terminal_growth=app.CURRENT_INFLATION_RATE,
        fade_rho=inputs["rho"],
        forecast_years=app.IMPLIED_NI_FORECAST_YEARS,
    )
    if not path:
        raise RuntimeError("PE-premium NI-growth path did not generate.")
    return float(path[0]["net_income"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", default="AAPL")
    parser.add_argument("--start-year", type=int, default=2022)
    parser.add_argument("--end-year", type=int, default=2024, help="Last base year; target is base year + 1.")
    args = parser.parse_args()

    company = app.find_company(args.ticker, app.load_companies(USER_AGENT))
    submissions = app.load_company_submissions(company.cik, USER_AGENT)
    facts = app.load_company_facts(company.cik, USER_AGENT)

    print(f"{company.ticker} one-year NI forecast backtest, USD billions")
    print("base->target | PE | rho | premium | Actual NI/g | PE-AE NI/g/err | PE-premium NI/g/err")

    pe_abs_errors: list[float] = []
    premium_abs_errors: list[float] = []
    for base_year in range(args.start_year, args.end_year + 1):
        inputs = load_backtest_inputs(company, submissions, facts, base_year)
        pe_pred = pe_implied_next_ni(inputs)
        premium_pred = pe_premium_next_ni(inputs)
        ni0 = inputs["ni0"]
        actual = inputs["actual_next_ni"]
        pe_error = pe_pred / actual - 1
        premium_error = premium_pred / actual - 1
        pe_abs_errors.append(abs(pe_error))
        premium_abs_errors.append(abs(premium_error))

        print(
            f"{base_year}->{base_year + 1} | "
            f"{inputs['pe']:.1f}x | {inputs['rho']:.3f} | "
            f"{inputs['pe'] - app.BASELINE_PE_MULTIPLE:.1f} | "
            f"{actual / 1e9:.2f}/{(actual / ni0 - 1) * 100:.1f}% | "
            f"{pe_pred / 1e9:.2f}/{(pe_pred / ni0 - 1) * 100:.1f}%/{pe_error * 100:.1f}% | "
            f"{premium_pred / 1e9:.2f}/{(premium_pred / ni0 - 1) * 100:.1f}%/{premium_error * 100:.1f}%"
        )

    print(f"MAPE_PE_implied={sum(pe_abs_errors) / len(pe_abs_errors) * 100:.2f}%")
    print(f"MAPE_PE_premium={sum(premium_abs_errors) / len(premium_abs_errors) * 100:.2f}%")


if __name__ == "__main__":
    main()
