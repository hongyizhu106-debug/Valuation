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
class CashFlowForecast:
    """Explicit free cash flow forecast.

    For FCFE, `cash_flows` should be free cash flows available to equity
    holders after interest, debt repayments/proceeds, and other financing
    effects.

    For FCFF, `cash_flows` should exclude financing effects and represent
    free cash flows available to all providers of capital.
    """

    cash_flows: list[ForecastRow]
    terminal_growth: TerminalGrowth | None = None


def fcfe_valuation(
    forecast: CashFlowForecast,
    cost_of_equity: float,
    shares_outstanding: float | None = None,
) -> dict[str, Any]:
    """Value equity directly using free cash flow to equity.

    Course mapping:
    - Week 9: levered model requires FCF available to shareholders.
    - Discount rate: cost of equity.
    - Equity value = PV(explicit FCFE) + PV(terminal FCFE).
    """

    equity_value, details = _discount_cash_flow_forecast(
        method="FCFE",
        forecast=forecast,
        discount_rate=cost_of_equity,
    )
    result_details = {
        **details,
        "discount_rate_type": "cost_of_equity",
        "shares_outstanding": shares_outstanding,
    }
    if shares_outstanding:
        result_details["value_per_share"] = equity_value / shares_outstanding
    return valuation_result("FCFE valuation", equity_value, result_details)


def fcff_valuation(
    forecast: CashFlowForecast,
    wacc: float,
    net_debt: float = 0.0,
    non_operating_assets: float = 0.0,
    shares_outstanding: float | None = None,
) -> dict[str, Any]:
    """Value enterprise / net operating assets using free cash flow to firm.

    Course mapping:
    - Week 9: unlevered model requires FCF before interest and debt
      transactions.
    - Discount rate: WACC.
    - Equity value = enterprise value - net debt + non-operating assets.
    """

    enterprise_value, details = _discount_cash_flow_forecast(
        method="FCFF",
        forecast=forecast,
        discount_rate=wacc,
    )
    equity_value = enterprise_value - net_debt + non_operating_assets
    result_details = {
        **details,
        "discount_rate_type": "wacc",
        "enterprise_value": enterprise_value,
        "net_debt": net_debt,
        "non_operating_assets": non_operating_assets,
        "shares_outstanding": shares_outstanding,
    }
    if shares_outstanding:
        result_details["value_per_share"] = equity_value / shares_outstanding
    return valuation_result("FCFF valuation", equity_value, result_details)


def _discount_cash_flow_forecast(
    method: str,
    forecast: CashFlowForecast,
    discount_rate: float,
) -> tuple[float, dict[str, Any]]:
    if not forecast.cash_flows:
        raise ValueError("cash_flows cannot be empty.")

    explicit_pv, explicit_details = sum_present_values(forecast.cash_flows, discount_rate)
    terminal_value = 0.0
    terminal_pv = 0.0
    terminal_details = None

    if forecast.terminal_growth and forecast.terminal_growth.use_terminal_value:
        final_row = max(forecast.cash_flows, key=lambda row: row.period)
        terminal_value = terminal_value_gordon(
            final_period_value=final_row.value,
            discount_rate=discount_rate,
            growth_rate=forecast.terminal_growth.growth_rate,
        )
        terminal_pv = present_value(terminal_value, discount_rate, final_row.period)
        terminal_details = {
            "terminal_method": "Gordon growth",
            "final_explicit_period": final_row.period,
            "final_period_value": final_row.value,
            "growth_rate": forecast.terminal_growth.growth_rate,
            "terminal_value_at_final_period": terminal_value,
            "terminal_present_value": terminal_pv,
        }

    total_value = explicit_pv + terminal_pv
    return total_value, {
        "cash_flow_type": method,
        "discount_rate": discount_rate,
        "explicit_present_value": explicit_pv,
        "explicit_forecast": explicit_details,
        "terminal": terminal_details,
        "terminal_present_value": terminal_pv,
    }
