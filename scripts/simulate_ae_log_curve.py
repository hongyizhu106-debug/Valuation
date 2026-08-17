from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import app  # noqa: E402


def value_for_growth(
    start_growth: float,
    *,
    net_income_ttm: float,
    book_equity: float,
    buyback_ttm: float,
    dividend_ttm: float,
    equity_cost: float,
    capital_return_growth: float,
    terminal_growth: float,
    log_base: float,
) -> dict[str, Any] | None:
    ni_growth_weights = [1.0, math.log(3) / math.log(4), math.log(2) / math.log(4)]
    net_income = net_income_ttm
    book_value = book_equity
    pv_abnormal_earnings = 0.0
    path: list[dict[str, float | str]] = []

    for year, weight in enumerate(ni_growth_weights, start=1):
        ni_growth = terminal_growth + (start_growth - terminal_growth) * weight
        net_income *= 1 + ni_growth
        buyback = buyback_ttm * ((1 + capital_return_growth) ** year)
        dividend = dividend_ttm * ((1 + capital_return_growth) ** year)
        abnormal_earnings = net_income - equity_cost * book_value
        ending_book_value = book_value + net_income - buyback - dividend
        pv_abnormal_earnings += abnormal_earnings / ((1 + equity_cost) ** year)
        path.append(
            {
                "year": float(year),
                "stage": "NI log-fade",
                "ni_growth": ni_growth,
                "net_income": net_income,
                "abnormal_earnings": abnormal_earnings,
                "buyback": buyback,
                "dividend": dividend,
                "beginning_book_value": book_value,
                "ending_book_value": ending_book_value,
            }
        )
        book_value = ending_book_value

    log_scale = float(path[2]["abnormal_earnings"]) - float(path[1]["abnormal_earnings"])
    if log_scale <= 0:
        return None

    year = 4
    net_income *= 1 + terminal_growth
    buyback = buyback_ttm * ((1 + capital_return_growth) ** year)
    dividend = dividend_ttm * ((1 + capital_return_growth) ** year)
    base_abnormal_earnings = net_income - equity_cost * book_value
    if base_abnormal_earnings <= 0:
        return None
    ending_book_value = book_value + net_income - buyback - dividend
    pv_abnormal_earnings += base_abnormal_earnings / ((1 + equity_cost) ** year)
    path.append(
        {
            "year": float(year),
            "stage": "NI stable bridge",
            "ni_growth": terminal_growth,
            "net_income": net_income,
            "abnormal_earnings": base_abnormal_earnings,
            "buyback": buyback,
            "dividend": dividend,
            "beginning_book_value": book_value,
            "ending_book_value": ending_book_value,
        }
    )
    book_value = ending_book_value

    for offset in range(1, 4):
        year = 4 + offset
        log_x = math.log(1 + offset, log_base)
        abnormal_earnings = base_abnormal_earnings + log_scale * log_x
        buyback = buyback_ttm * ((1 + capital_return_growth) ** year)
        dividend = dividend_ttm * ((1 + capital_return_growth) ** year)
        net_income = abnormal_earnings + equity_cost * book_value
        ending_book_value = book_value + net_income - buyback - dividend
        pv_abnormal_earnings += abnormal_earnings / ((1 + equity_cost) ** year)
        path.append(
            {
                "year": float(year),
                "stage": "AE log-level",
                "log_x": log_x,
                "net_income": net_income,
                "abnormal_earnings": abnormal_earnings,
                "buyback": buyback,
                "dividend": dividend,
                "beginning_book_value": book_value,
                "ending_book_value": ending_book_value,
            }
        )
        book_value = ending_book_value

    terminal_year = 8
    terminal_abnormal_earnings = float(path[-1]["abnormal_earnings"]) * (1 + terminal_growth)
    terminal_value = terminal_abnormal_earnings / (equity_cost - terminal_growth)
    pv_terminal = terminal_value / ((1 + equity_cost) ** (terminal_year - 1))
    equity_value = book_equity + pv_abnormal_earnings + pv_terminal
    if not math.isfinite(equity_value):
        return None

    return {
        "start_growth": start_growth,
        "log_scale": log_scale,
        "path": path,
        "terminal": {
            "year": terminal_year,
            "abnormal_earnings": terminal_abnormal_earnings,
            "terminal_value": terminal_value,
            "pv_terminal": pv_terminal,
        },
        "pv_abnormal_earnings": pv_abnormal_earnings,
        "equity_value": equity_value,
    }


def solve_market_implied_growth(
    market_value: float,
    **model_inputs: float,
) -> dict[str, Any] | None:
    candidates: list[tuple[float, float]] = []
    search_low, search_high = -0.9, 1.5
    for index in range(241):
        start_growth = search_low + (search_high - search_low) * index / 240
        result = value_for_growth(start_growth, **model_inputs)
        if result is not None:
            candidates.append((start_growth, float(result["equity_value"])))

    bracket: tuple[float, float] | None = None
    for left, right in zip(candidates, candidates[1:]):
        if (left[1] - market_value) * (right[1] - market_value) <= 0:
            bracket = (left[0], right[0])
            break
    if bracket is None:
        return None

    low, high = bracket
    for _ in range(120):
        mid = (low + high) / 2
        result = value_for_growth(mid, **model_inputs)
        if result is None:
            low = mid
            continue
        if float(result["equity_value"]) < market_value:
            low = mid
        else:
            high = mid

    return value_for_growth((low + high) / 2, **model_inputs)


def billions(value: float) -> str:
    return f"${value / 1_000_000_000:,.2f}B"


def historical_ttm_series(
    company_facts: dict[str, Any],
    filings: list[Any],
    concepts: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for filing in sorted(filings, key=lambda item: item.report_date):
        value, concept = app.extract_ttm_value(company_facts, filing, concepts)
        if isinstance(value, (int, float)) and value != 0:
            rows.append(
                {
                    "report_date": filing.report_date,
                    "value": abs(float(value)),
                    "concept": concept,
                }
            )
    return rows


def add_yoy_growth(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prior_value: float | None = None
    for row in rows:
        value = float(row["value"])
        row["yoy_growth"] = value / prior_value - 1 if prior_value and prior_value > 0 else None
        prior_value = value
    return rows


def maximum_historical_growth(rows: list[dict[str, Any]]) -> float | None:
    growth_rates = [float(row["yoy_growth"]) for row in rows if isinstance(row.get("yoy_growth"), (int, float))]
    return max(growth_rates) if growth_rates else None


def load_apple_inputs(user_agent: str) -> dict[str, Any]:
    company = app.find_company("AAPL", app.load_companies(user_agent))
    submissions = app.load_company_submissions(company.cik, user_agent)
    filings, _ = app.find_same_type_filings_for_vertical_compare(
        submissions=submissions,
        company=company,
        user_agent=user_agent,
        form="10-Q",
        year=2026,
        quarter="Q2",
    )
    filing = next(item for item in filings if item.report_date.startswith("2026-"))
    prior_filing = next((item for item in filings if item.report_date.startswith("2025-")), None)
    company_facts = app.load_company_facts(company.cik, user_agent)
    monthly_pe_rows = app.build_monthly_pe_rows(company_facts, filing.ticker, filings)
    market_pe = app.latest_market_pe(monthly_pe_rows)
    net_income_ttm, net_income_concept = app.extract_ttm_value(company_facts, filing, ["NetIncomeLoss"])
    prior_net_income_ttm, _ = (
        app.extract_ttm_value(company_facts, prior_filing, ["NetIncomeLoss"])
        if prior_filing
        else (None, None)
    )
    buyback_ttm, buyback_concept = app.extract_ttm_value(
        company_facts,
        filing,
        ["PaymentsForRepurchaseOfCommonStock", "StockRepurchasedAndRetiredDuringPeriodValue"],
    )
    dividend_ttm, dividend_concept = app.extract_ttm_value(
        company_facts,
        filing,
        ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock", "Dividends"],
    )
    equity_entry = app.extract_equity_entry(company_facts, filing)
    if not market_pe or not net_income_ttm or not equity_entry:
        raise RuntimeError("Missing PE, TTM net income, or book equity for the Apple example.")

    buyback_history = add_yoy_growth(
        historical_ttm_series(
            company_facts,
            filings,
            ["PaymentsForRepurchaseOfCommonStock", "StockRepurchasedAndRetiredDuringPeriodValue"],
        )
    )
    dividend_history = add_yoy_growth(
        historical_ttm_series(
            company_facts,
            filings,
            ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock", "Dividends"],
        )
    )

    return {
        "filing": filing,
        "market_pe": float(market_pe),
        "pe_month": monthly_pe_rows[-1]["month"],
        "net_income_ttm": float(net_income_ttm),
        "prior_net_income_ttm": float(prior_net_income_ttm) if prior_net_income_ttm else None,
        "ttm_net_income_growth": (
            float(net_income_ttm) / float(prior_net_income_ttm) - 1
            if prior_net_income_ttm
            else None
        ),
        "net_income_concept": net_income_concept,
        "book_equity": float(equity_entry["raw_value"]),
        "buyback_ttm": abs(float(buyback_ttm or 0.0)),
        "buyback_concept": buyback_concept,
        "buyback_history": buyback_history,
        "maximum_buyback_growth": maximum_historical_growth(buyback_history),
        "dividend_ttm": abs(float(dividend_ttm or 0.0)),
        "dividend_concept": dividend_concept,
        "dividend_history": dividend_history,
        "maximum_dividend_growth": maximum_historical_growth(dividend_history),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate an AE level forecast using an increasing log curve.")
    parser.add_argument("--equity-cost", type=float, default=0.10)
    parser.add_argument("--capital-return-growth", type=float, default=0.035)
    parser.add_argument("--terminal-growth", type=float, default=0.035)
    parser.add_argument("--log-base", type=float, default=2.0)
    parser.add_argument(
        "--user-agent",
        default=os.environ.get("SEC_USER_AGENT") or app.DEFAULT_SEC_USER_AGENT,
    )
    args = parser.parse_args()
    if args.log_base <= 1:
        parser.error("--log-base must be greater than 1.")
    if args.equity_cost <= args.terminal_growth:
        parser.error("--equity-cost must be greater than --terminal-growth.")

    source = load_apple_inputs(args.user_agent)
    market_value = source["market_pe"] * source["net_income_ttm"]
    model_inputs = {
        "net_income_ttm": source["net_income_ttm"],
        "book_equity": source["book_equity"],
        "buyback_ttm": source["buyback_ttm"],
        "dividend_ttm": source["dividend_ttm"],
        "equity_cost": args.equity_cost,
        "capital_return_growth": args.capital_return_growth,
        "terminal_growth": args.terminal_growth,
        "log_base": args.log_base,
    }
    result = solve_market_implied_growth(market_value, **model_inputs)
    if result is None:
        raise RuntimeError("No market-implied growth solution was found in the -90% to 150% range.")

    old_growth, _, _ = app.solve_implied_ae_persistence_model(
        market_value=market_value,
        net_income_ttm=source["net_income_ttm"],
        book_equity=source["book_equity"],
        buyback_base=source["buyback_ttm"],
        dividend_ttm=source["dividend_ttm"],
        equity_cost=args.equity_cost,
        terminal_growth=args.terminal_growth,
        buyback_growth=args.capital_return_growth,
        dividend_growth=args.capital_return_growth,
    )

    print("SOURCE DATA")
    print(f"Company: Apple Inc. ({source['filing'].ticker})")
    print(f"Filing: {source['filing'].form}, report {source['filing'].report_date}, filed {source['filing'].filing_date}")
    print(f"Market PE: {source['market_pe']:.4f}x ({source['pe_month']})")
    print(f"Market-implied equity value: {billions(market_value)}")
    print(f"TTM net income: {billions(source['net_income_ttm'])} ({source['net_income_concept']})")
    print(f"Book equity: {billions(source['book_equity'])}")
    print(f"TTM buyback: {billions(source['buyback_ttm'])} ({source['buyback_concept']})")
    print(f"TTM dividend: {billions(source['dividend_ttm'])} ({source['dividend_concept']})")

    print("\nASSUMPTIONS")
    print(f"Equity cost: {args.equity_cost:.2%}")
    print(f"Buyback/dividend growth: {args.capital_return_growth:.2%}")
    print(f"Terminal AE growth: {args.terminal_growth:.2%}")
    print(f"AE log curve: AE_(4+t) = AE_4 + K * log_base(1+t), base={args.log_base:g}")
    print("K = AE_3 - AE_2")

    print("\nRESULT")
    if old_growth is not None:
        print(f"Previous AE log-return model implied initial NI growth: {old_growth:.2%}")
    print(f"AE log-level model implied initial NI growth: {result['start_growth']:.2%}")
    print(f"K: {billions(result['log_scale'])}")
    print("\nYEAR-BY-YEAR")
    for row in result["path"]:
        extra = f", log_x={row['log_x']:.4f}" if "log_x" in row else ""
        print(
            f"Year {int(row['year'])}: {row['stage']}, "
            f"NI={billions(float(row['net_income']))}, "
            f"AE={billions(float(row['abnormal_earnings']))}, "
            f"buyback={billions(float(row['buyback']))}, "
            f"dividend={billions(float(row['dividend']))}, "
            f"ending BVE={billions(float(row['ending_book_value']))}{extra}"
        )

    terminal = result["terminal"]
    print(
        f"Year {terminal['year']} terminal entry: "
        f"AE={billions(terminal['abnormal_earnings'])}, "
        f"terminal value={billions(terminal['terminal_value'])}"
    )
    print("\nRECONCILIATION")
    print(f"Opening book equity: {billions(source['book_equity'])}")
    print(f"PV of Year 1-7 AE: {billions(result['pv_abnormal_earnings'])}")
    print(f"PV of terminal value: {billions(terminal['pv_terminal'])}")
    print(f"Model equity value: {billions(result['equity_value'])}")
    print(f"Market-implied equity value: {billions(market_value)}")


if __name__ == "__main__":
    main()
