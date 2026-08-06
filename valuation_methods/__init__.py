"""Valuation method library for the financial statement analysis dashboard.

The package currently implements:

- FCF / DCF valuation:
  - FCFE: value equity directly using free cash flow to equity.
  - FCFF: value enterprise / net operating assets using free cash flow to firm.
- ACF / AE valuation:
  - Abnormal earnings / residual income model.
  - Abnormal NOPAT model for valuing operating assets.

The naming keeps `ACF` as a user-facing alias, but the course documents in
`FMI/` mainly use the terms "abnormal earnings", "residual income", and
"abnormal NOPAT".
"""

from .acf import (
    AbnormalEarningsForecast,
    AbnormalNopatForecast,
    abnormal_earnings_valuation,
    abnormal_nopat_valuation,
)
from .common import ForecastRow, TerminalGrowth, present_value, terminal_value_gordon
from .fcf import CashFlowForecast, fcfe_valuation, fcff_valuation

__all__ = [
    "AbnormalEarningsForecast",
    "AbnormalNopatForecast",
    "CashFlowForecast",
    "ForecastRow",
    "TerminalGrowth",
    "abnormal_earnings_valuation",
    "abnormal_nopat_valuation",
    "fcfe_valuation",
    "fcff_valuation",
    "present_value",
    "terminal_value_gordon",
]
