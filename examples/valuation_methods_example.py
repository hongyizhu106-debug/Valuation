from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from valuation_methods import (
    AbnormalEarningsForecast,
    AbnormalNopatForecast,
    CashFlowForecast,
    ForecastRow,
    TerminalGrowth,
    abnormal_earnings_valuation,
    abnormal_nopat_valuation,
    fcfe_valuation,
    fcff_valuation,
)


def main() -> None:
    # Example numbers are deliberately simple and are not investment advice.
    fcfe = CashFlowForecast(
        cash_flows=[
            ForecastRow(1, 110),
            ForecastRow(2, 125),
            ForecastRow(3, 140),
        ],
        terminal_growth=TerminalGrowth(growth_rate=0.03),
    )
    fcff = CashFlowForecast(
        cash_flows=[
            ForecastRow(1, 150),
            ForecastRow(2, 165),
            ForecastRow(3, 180),
        ],
        terminal_growth=TerminalGrowth(growth_rate=0.03),
    )

    abnormal_earnings = AbnormalEarningsForecast(
        opening_book_value_equity=900,
        net_income_forecasts=[
            ForecastRow(1, 120),
            ForecastRow(2, 135),
            ForecastRow(3, 150),
        ],
        opening_bve_by_period=[
            ForecastRow(1, 900),
            ForecastRow(2, 980),
            ForecastRow(3, 1_070),
        ],
        terminal_growth=TerminalGrowth(growth_rate=0.02),
    )

    abnormal_nopat = AbnormalNopatForecast(
        opening_book_value_noa=1_300,
        nopat_forecasts=[
            ForecastRow(1, 160),
            ForecastRow(2, 180),
            ForecastRow(3, 200),
        ],
        opening_bvnoa_by_period=[
            ForecastRow(1, 1_300),
            ForecastRow(2, 1_390),
            ForecastRow(3, 1_480),
        ],
        terminal_growth=TerminalGrowth(growth_rate=0.02),
    )

    results = {
        "fcfe": fcfe_valuation(fcfe, cost_of_equity=0.10, shares_outstanding=100),
        "fcff": fcff_valuation(fcff, wacc=0.085, net_debt=300, shares_outstanding=100),
        "abnormal_earnings": abnormal_earnings_valuation(
            abnormal_earnings,
            cost_of_equity=0.10,
            shares_outstanding=100,
        ),
        "abnormal_nopat": abnormal_nopat_valuation(
            abnormal_nopat,
            wacc=0.085,
            net_debt=300,
            shares_outstanding=100,
        ),
    }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
