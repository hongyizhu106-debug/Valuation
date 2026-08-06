from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ForecastRow:
    """One forecast-period value to discount.

    `period` is 1-based: period 1 is one year from the valuation date.
    """

    period: int
    value: float
    label: str = ""


@dataclass(frozen=True)
class TerminalGrowth:
    """Gordon-growth terminal value assumptions.

    The terminal cash flow / abnormal earnings is grown from the final explicit
    forecast period by `growth_rate`, then capitalized at discount_rate - g.
    """

    growth_rate: float
    use_terminal_value: bool = True


def validate_rate(name: str, rate: float) -> None:
    if rate <= -1:
        raise ValueError(f"{name} must be greater than -100%.")


def validate_terminal_growth(discount_rate: float, growth_rate: float) -> None:
    validate_rate("discount_rate", discount_rate)
    validate_rate("growth_rate", growth_rate)
    if growth_rate >= discount_rate:
        raise ValueError("Terminal growth rate must be lower than discount rate.")


def present_value(value: float, discount_rate: float, period: int) -> float:
    if period < 0:
        raise ValueError("period must be non-negative.")
    validate_rate("discount_rate", discount_rate)
    return value / ((1 + discount_rate) ** period)


def terminal_value_gordon(final_period_value: float, discount_rate: float, growth_rate: float) -> float:
    """Terminal value at the final explicit forecast date."""

    validate_terminal_growth(discount_rate, growth_rate)
    next_period_value = final_period_value * (1 + growth_rate)
    return next_period_value / (discount_rate - growth_rate)


def sum_present_values(rows: list[ForecastRow], discount_rate: float) -> tuple[float, list[dict[str, Any]]]:
    details: list[dict[str, Any]] = []
    total = 0.0
    for row in rows:
        pv = present_value(row.value, discount_rate, row.period)
        total += pv
        details.append(
            {
                "period": row.period,
                "label": row.label or f"Year {row.period}",
                "value": row.value,
                "discount_rate": discount_rate,
                "present_value": pv,
            }
        )
    return total, details


def valuation_result(method: str, value: float, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "method": method,
        "value": value,
        "details": details,
    }
