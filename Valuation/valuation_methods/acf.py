from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .common import (
    ForecastRow,
    TerminalGrowth,
    present_value,
    sum_present_values,
    terminal_value_gordon,
    valuation_result,
)


@dataclass(frozen=True)
class AbnormalEarningsForecast:
    """Forecast inputs for abnormal earnings / residual income valuation.

    Abnormal earnings = net income - cost of equity * opening book value of equity.
    Equity value = opening BVE + PV(future abnormal earnings).
    """

    opening_book_value_equity: float
    net_income_forecasts: list[ForecastRow]
    opening_bve_by_period: list[ForecastRow]
    terminal_growth: TerminalGrowth | None = None


@dataclass(frozen=True)
class AbnormalNopatForecast:
    """Forecast inputs for abnormal NOPAT valuation.

    Abnormal NOPAT = NOPAT - WACC * opening book value of net operating assets.
    Asset / NOA value = opening BVNOA + PV(future abnormal NOPAT).
    Equity value = asset value - net debt + non-operating assets.
    """

    opening_book_value_noa: float
    nopat_forecasts: list[ForecastRow]
    opening_bvnoa_by_period: list[ForecastRow]
    terminal_growth: TerminalGrowth | None = None


def abnormal_earnings_valuation(
    forecast: AbnormalEarningsForecast,
    cost_of_equity: float,
    shares_outstanding: float | None = None,
) -> dict[str, Any]:
    """Value equity using abnormal earnings / residual income.

    Course mapping:
    - Week 10: "Fundamental value of equity = Book value of equity + PV of
      future abnormal earnings".
    - Abnormal earnings = net income - capital charge.
    - Capital charge = cost of equity * opening book value of equity.
    """

    abnormal_rows = _build_abnormal_rows(
        performance_rows=forecast.net_income_forecasts,
        capital_base_rows=forecast.opening_bve_by_period,
        capital_charge_rate=cost_of_equity,
        performance_label="Net income",
        capital_base_label="Opening BVE",
        abnormal_label="Abnormal earnings",
    )
    pv_abnormal, details = _discount_abnormal_rows(
        abnormal_rows=abnormal_rows,
        discount_rate=cost_of_equity,
        terminal_growth=forecast.terminal_growth,
    )
    equity_value = forecast.opening_book_value_equity + pv_abnormal
    result_details = {
        **details,
        "opening_book_value_equity": forecast.opening_book_value_equity,
        "discount_rate_type": "cost_of_equity",
        "pv_abnormal_earnings": pv_abnormal,
        "shares_outstanding": shares_outstanding,
    }
    if shares_outstanding:
        result_details["value_per_share"] = equity_value / shares_outstanding
    return valuation_result("ACF / abnormal earnings valuation", equity_value, result_details)


def abnormal_nopat_valuation(
    forecast: AbnormalNopatForecast,
    wacc: float,
    net_debt: float = 0.0,
    non_operating_assets: float = 0.0,
    shares_outstanding: float | None = None,
) -> dict[str, Any]:
    """Value operating assets using abnormal NOPAT, then bridge to equity."""

    abnormal_rows = _build_abnormal_rows(
        performance_rows=forecast.nopat_forecasts,
        capital_base_rows=forecast.opening_bvnoa_by_period,
        capital_charge_rate=wacc,
        performance_label="NOPAT",
        capital_base_label="Opening BVNOA",
        abnormal_label="Abnormal NOPAT",
    )
    pv_abnormal, details = _discount_abnormal_rows(
        abnormal_rows=abnormal_rows,
        discount_rate=wacc,
        terminal_growth=forecast.terminal_growth,
    )
    asset_value = forecast.opening_book_value_noa + pv_abnormal
    equity_value = asset_value - net_debt + non_operating_assets
    result_details = {
        **details,
        "opening_book_value_noa": forecast.opening_book_value_noa,
        "discount_rate_type": "wacc",
        "pv_abnormal_nopat": pv_abnormal,
        "asset_value": asset_value,
        "net_debt": net_debt,
        "non_operating_assets": non_operating_assets,
        "shares_outstanding": shares_outstanding,
    }
    if shares_outstanding:
        result_details["value_per_share"] = equity_value / shares_outstanding
    return valuation_result("ACF / abnormal NOPAT valuation", equity_value, result_details)


def _build_abnormal_rows(
    performance_rows: list[ForecastRow],
    capital_base_rows: list[ForecastRow],
    capital_charge_rate: float,
    performance_label: str,
    capital_base_label: str,
    abnormal_label: str,
) -> list[ForecastRow]:
    if len(performance_rows) != len(capital_base_rows):
        raise ValueError("performance rows and capital-base rows must have the same length.")
    if not performance_rows:
        raise ValueError("forecast rows cannot be empty.")

    capital_base_by_period = {row.period: row for row in capital_base_rows}
    abnormal_rows: list[ForecastRow] = []
    for performance in performance_rows:
        capital_base = capital_base_by_period.get(performance.period)
        if not capital_base:
            raise ValueError(f"Missing capital base for period {performance.period}.")
        capital_charge = capital_charge_rate * capital_base.value
        abnormal_value = performance.value - capital_charge
        abnormal_rows.append(
            ForecastRow(
                period=performance.period,
                value=abnormal_value,
                label=(
                    f"{abnormal_label}: {performance_label} {performance.value:,.2f} "
                    f"- {capital_charge_rate:.2%} * {capital_base_label} {capital_base.value:,.2f}"
                ),
            )
        )
    return abnormal_rows


def _discount_abnormal_rows(
    abnormal_rows: list[ForecastRow],
    discount_rate: float,
    terminal_growth: TerminalGrowth | None,
) -> tuple[float, dict[str, Any]]:
    explicit_pv, explicit_details = sum_present_values(abnormal_rows, discount_rate)
    terminal_value = 0.0
    terminal_pv = 0.0
    terminal_details = None

    if terminal_growth and terminal_growth.use_terminal_value:
        final_row = max(abnormal_rows, key=lambda row: row.period)
        terminal_value = terminal_value_gordon(
            final_period_value=final_row.value,
            discount_rate=discount_rate,
            growth_rate=terminal_growth.growth_rate,
        )
        terminal_pv = present_value(terminal_value, discount_rate, final_row.period)
        terminal_details = {
            "terminal_method": "Gordon growth on abnormal performance",
            "final_explicit_period": final_row.period,
            "final_abnormal_value": final_row.value,
            "growth_rate": terminal_growth.growth_rate,
            "terminal_value_at_final_period": terminal_value,
            "terminal_present_value": terminal_pv,
        }

    return explicit_pv + terminal_pv, {
        "discount_rate": discount_rate,
        "explicit_abnormal_present_value": explicit_pv,
        "explicit_abnormal_forecast": explicit_details,
        "terminal": terminal_details,
        "terminal_present_value": terminal_pv,
    }
