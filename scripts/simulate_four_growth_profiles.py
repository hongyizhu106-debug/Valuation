from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import app
from simulate_ae_log_curve import billions, load_apple_inputs


@dataclass(frozen=True)
class GrowthProfile:
    key: str
    label: str
    kind: str
    horizon: int
    log_base: float | None = None


PROFILES = [
    GrowthProfile("blue_chip", "1. Blue-chip stable", "constant", 4),
    GrowthProfile("mature_growth", "2. Mature growth", "log", 5, 2.0),
    GrowthProfile("high_growth", "3. High growth", "log", 7, 4.0),
    GrowthProfile("small_expansion", "4. Small expansion", "log", 7, 8.0),
]
AE_TAIL_YEARS = 3


def normalized_log_level(year: int, horizon: int, log_base: float) -> float:
    z = year / horizon
    return math.log(1 + (log_base - 1) * z, log_base)


def evaluate_profile(
    profile: GrowthProfile,
    parameter: float,
    *,
    net_income_ttm: float,
    book_equity: float,
    buyback_ttm: float,
    dividend_ttm: float,
    equity_cost: float,
    buyback_growth: float,
    dividend_growth: float,
    terminal_growth: float,
) -> dict[str, Any] | None:
    net_income = net_income_ttm
    book_value = book_equity
    pv_abnormal_earnings = 0.0
    path: list[dict[str, Any]] = []

    for year in range(1, profile.horizon + 1):
        if profile.kind == "constant":
            forecast_net_income = net_income_ttm * ((1 + parameter) ** year)
            curve_level = float(year)
        else:
            if profile.log_base is None:
                return None
            curve_level = normalized_log_level(year, profile.horizon, profile.log_base)
            forecast_net_income = net_income_ttm * (1 + parameter * curve_level)

        if forecast_net_income <= 0:
            return None
        ni_growth = forecast_net_income / net_income - 1
        buyback = buyback_ttm * ((1 + buyback_growth) ** year)
        dividend = dividend_ttm * ((1 + dividend_growth) ** year)
        abnormal_earnings = forecast_net_income - equity_cost * book_value
        ending_book_value = book_value + forecast_net_income - buyback - dividend
        pv_abnormal_earnings += abnormal_earnings / ((1 + equity_cost) ** year)
        path.append(
            {
                "year": float(year),
                "stage": "profile",
                "curve_level": curve_level,
                "ni_growth": ni_growth,
                "net_income": forecast_net_income,
                "beginning_book_value": book_value,
                "abnormal_earnings": abnormal_earnings,
                "buyback": buyback,
                "dividend": dividend,
                "ending_book_value": ending_book_value,
            }
        )
        net_income = forecast_net_income
        book_value = ending_book_value

    for year in range(profile.horizon + 1, profile.horizon + AE_TAIL_YEARS + 1):
        net_income *= 1 + terminal_growth
        buyback = buyback_ttm * ((1 + buyback_growth) ** year)
        dividend = dividend_ttm * ((1 + dividend_growth) ** year)
        abnormal_earnings = net_income - equity_cost * book_value
        ending_book_value = book_value + net_income - buyback - dividend
        pv_abnormal_earnings += abnormal_earnings / ((1 + equity_cost) ** year)
        path.append(
            {
                "year": float(year),
                "stage": "AE tail",
                "ni_growth": terminal_growth,
                "net_income": net_income,
                "beginning_book_value": book_value,
                "abnormal_earnings": abnormal_earnings,
                "buyback": buyback,
                "dividend": dividend,
                "ending_book_value": ending_book_value,
            }
        )
        book_value = ending_book_value

    terminal_year = profile.horizon + AE_TAIL_YEARS + 1
    terminal_net_income = net_income * (1 + terminal_growth)
    terminal_abnormal_earnings = terminal_net_income - equity_cost * book_value
    if terminal_abnormal_earnings <= 0:
        return None
    terminal_value = terminal_abnormal_earnings / (equity_cost - terminal_growth)
    pv_terminal = terminal_value / ((1 + equity_cost) ** (terminal_year - 1))
    terminal_buyback = buyback_ttm * ((1 + buyback_growth) ** terminal_year)
    terminal_dividend = dividend_ttm * ((1 + dividend_growth) ** terminal_year)
    terminal_ending_book_value = book_value + terminal_net_income - terminal_buyback - terminal_dividend
    first_negative_bve_year = next(
        (int(row["year"]) for row in path if float(row["ending_book_value"]) < 0),
        None,
    )
    if first_negative_bve_year is None and terminal_ending_book_value < 0:
        first_negative_bve_year = terminal_year
    equity_value = book_equity + pv_abnormal_earnings + pv_terminal
    if not math.isfinite(equity_value):
        return None

    return {
        "profile": profile,
        "parameter": parameter,
        "path": path,
        "terminal": {
            "year": float(terminal_year),
            "net_income": terminal_net_income,
            "abnormal_earnings": terminal_abnormal_earnings,
            "terminal_value": terminal_value,
            "pv_terminal": pv_terminal,
            "buyback": terminal_buyback,
            "dividend": terminal_dividend,
            "ending_book_value": terminal_ending_book_value,
        },
        "pv_abnormal_earnings": pv_abnormal_earnings,
        "equity_value": equity_value,
        "first_negative_bve_year": first_negative_bve_year,
    }


def solve_profile(
    profile: GrowthProfile,
    market_value: float,
    **model_inputs: float,
) -> dict[str, Any] | None:
    search_low, search_high = (-0.9, 1.5) if profile.kind == "constant" else (-0.9, 10.0)
    candidates: list[tuple[float, float]] = []
    for index in range(401):
        parameter = search_low + (search_high - search_low) * index / 400
        result = evaluate_profile(profile, parameter, **model_inputs)
        if result is not None:
            candidates.append((parameter, float(result["equity_value"])))

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
        result = evaluate_profile(profile, mid, **model_inputs)
        if result is None:
            low = mid
            continue
        if float(result["equity_value"]) < market_value:
            low = mid
        else:
            high = mid

    return evaluate_profile(profile, (low + high) / 2, **model_inputs)


def formula_label(profile: GrowthProfile) -> str:
    if profile.kind == "constant":
        return f"constant annual growth, H={profile.horizon}"
    return f"normalized log level, a={profile.log_base:g}, H={profile.horizon}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare four market-implied Apple NI growth profiles.")
    parser.add_argument("--equity-cost", type=float, default=0.10)
    parser.add_argument(
        "--buyback-growth",
        type=float,
        help="Annual nominal buyback growth; defaults to the dashboard CPI assumption.",
    )
    parser.add_argument("--dividend-growth", type=float)
    parser.add_argument("--terminal-growth", type=float, default=0.035)
    parser.add_argument(
        "--user-agent",
        default=os.environ.get("SEC_USER_AGENT") or app.DEFAULT_SEC_USER_AGENT,
    )
    args = parser.parse_args()
    if args.equity_cost <= args.terminal_growth:
        parser.error("--equity-cost must be greater than --terminal-growth.")

    source = load_apple_inputs(args.user_agent)
    buyback_growth = (
        args.buyback_growth
        if args.buyback_growth is not None
        else app.CURRENT_INFLATION_RATE
    )
    dividend_growth = args.dividend_growth
    if dividend_growth is None:
        dividend_growth = source["maximum_dividend_growth"]
    if dividend_growth is None:
        raise RuntimeError("Four same-period growth intervals are required for the dividend forecast.")
    dividend_intervals = [row for row in source["dividend_history"] if row["yoy_growth"] is not None]
    if len(dividend_intervals) < 4:
        raise RuntimeError("Five same-period TTM observations are required to calculate dividend growth.")
    market_value = source["market_pe"] * source["net_income_ttm"]
    model_inputs = {
        "net_income_ttm": source["net_income_ttm"],
        "book_equity": source["book_equity"],
        "buyback_ttm": source["buyback_ttm"],
        "dividend_ttm": source["dividend_ttm"],
        "equity_cost": args.equity_cost,
        "buyback_growth": buyback_growth,
        "dividend_growth": dividend_growth,
        "terminal_growth": args.terminal_growth,
    }

    results: list[dict[str, Any]] = []
    for profile in PROFILES:
        result = solve_profile(profile, market_value, **model_inputs)
        if result is not None:
            if not math.isclose(float(result["equity_value"]), market_value, rel_tol=1e-10):
                raise RuntimeError(f"Valuation reconciliation failed for {profile.label}.")
            results.append(result)

    print("SOURCE DATA")
    print(f"Company: Apple Inc. ({source['filing'].ticker})")
    print(f"Filing: {source['filing'].form}, report {source['filing'].report_date}, filed {source['filing'].filing_date}")
    print(f"Market PE: {source['market_pe']:.4f}x ({source['pe_month']})")
    print(f"Market-implied equity value: {billions(market_value)}")
    print(f"TTM net income: {billions(source['net_income_ttm'])}")
    if source["ttm_net_income_growth"] is not None:
        print(f"Actual TTM NI growth at the filing: {source['ttm_net_income_growth']:.2%}")
    print(f"Book equity: {billions(source['book_equity'])}")
    print(f"TTM buyback: {billions(source['buyback_ttm'])}")
    print(f"TTM dividend: {billions(source['dividend_ttm'])}")

    print("\nHISTORICAL CAPITAL RETURNS")
    for row in source["buyback_history"]:
        growth = "n/a" if row["yoy_growth"] is None else f"{row['yoy_growth']:.2%}"
        print(f"Buyback {row['report_date']}: {billions(row['value'])}, YoY={growth}")
    for row in source["dividend_history"]:
        growth = "n/a" if row["yoy_growth"] is None else f"{row['yoy_growth']:.2%}"
        print(f"Dividend {row['report_date']}: {billions(row['value'])}, YoY={growth}")

    print("\nCOMMON ASSUMPTIONS")
    print(f"Equity cost: {args.equity_cost:.2%}")
    buyback_source = (
        "command-line override"
        if args.buyback_growth is not None
        else "dashboard CPI-U assumption, BLS 2026-06"
    )
    print(f"Forecast buyback growth: {buyback_growth:.2%} ({buyback_source})")
    print(f"Forecast dividend growth: {dividend_growth:.2%} (maximum of four same-period YoY intervals)")
    print(f"NI growth during the three-year AE tail: {args.terminal_growth:.2%}")
    print("Every projected buyback and dividend is subtracted directly from that year's ending BVE.")

    print("\nPROFILE SUMMARY")
    for result in results:
        profile = result["profile"]
        path = result["path"]
        terminal = result["terminal"]
        first_growth = float(path[0]["ni_growth"])
        final_net_income = float(path[profile.horizon - 1]["net_income"])
        terminal_share = float(terminal["pv_terminal"]) / float(result["equity_value"])
        if profile.kind == "constant":
            parameter_text = f"annual g={result['parameter']:.2%}"
        else:
            parameter_text = f"cumulative uplift C={result['parameter']:.2%}"
        bve_status = (
            f"BVE<0 in Year {result['first_negative_bve_year']}"
            if result["first_negative_bve_year"] is not None
            else "BVE remains positive"
        )
        print(
            f"{profile.label}: {formula_label(profile)}, {parameter_text}, "
            f"Year-1 growth={first_growth:.2%}, NI_H={billions(final_net_income)}, "
            f"terminal share={terminal_share:.1%}, {bve_status}"
        )

    for result in results:
        profile = result["profile"]
        print(f"\n{profile.label.upper()} | {formula_label(profile)}")
        for row in result["path"]:
            stage = "profile" if row["stage"] == "profile" else "AE tail"
            print(
                f"Year {int(row['year'])} [{stage}]: NI growth={row['ni_growth']:.2%}, "
                f"NI={billions(row['net_income'])}, AE={billions(row['abnormal_earnings'])}, "
                f"buyback={billions(row['buyback'])}, dividend={billions(row['dividend'])}, "
                f"ending BVE={billions(row['ending_book_value'])}"
            )
        terminal = result["terminal"]
        print(
            f"Year {int(terminal['year'])} terminal: NI={billions(terminal['net_income'])}, "
            f"AE={billions(terminal['abnormal_earnings'])}, "
            f"buyback={billions(terminal['buyback'])}, dividend={billions(terminal['dividend'])}, "
            f"ending BVE={billions(terminal['ending_book_value'])}"
        )
        print(
            f"Reconciliation: BVE0={billions(source['book_equity'])} + "
            f"PV(AE)={billions(result['pv_abnormal_earnings'])} + "
            f"PV(TV)={billions(terminal['pv_terminal'])} = "
            f"{billions(result['equity_value'])}"
        )

    if results and source["ttm_net_income_growth"] is not None:
        closest = min(
            results,
            key=lambda item: abs(float(item["path"][0]["ni_growth"]) - source["ttm_net_income_growth"]),
        )
        print("\nOBSERVATION")
        print(
            f"The closest Year-1 requirement to actual TTM growth is {closest['profile'].label}: "
            f"{closest['path'][0]['ni_growth']:.2%} versus {source['ttm_net_income_growth']:.2%}."
        )
        invalid_bve_results = [item for item in results if item["first_negative_bve_year"] is not None]
        if invalid_bve_results:
            labels = ", ".join(item["profile"].label for item in invalid_bve_results)
            print(f"Warning: CPI-linked buyback growth produces negative BVE for {labels}.")
        print("This is a curve-fit comparison, not an automatic company classification or investment conclusion.")


if __name__ == "__main__":
    main()
