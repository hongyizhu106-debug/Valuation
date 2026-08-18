from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from valuation_methods import (  # noqa: E402
    AbnormalEarningsForecast,
    ForecastRow,
    TerminalGrowth,
    abnormal_earnings_valuation,
)


def main() -> None:
    """Run a small abnormal-earnings example with explicit assumptions."""

    cost_of_equity = 0.10
    shares_outstanding = 100
    forecast = AbnormalEarningsForecast(
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

    result = abnormal_earnings_valuation(
        forecast,
        cost_of_equity=cost_of_equity,
        shares_outstanding=shares_outstanding,
    )
    details = result["details"]

    public_summary = {
        "model": "abnormal earnings / residual income",
        "formula": "Equity value = opening BVE + PV(future AE); AE = NI - cost_of_equity * opening BVE",
        "assumptions": {
            "opening_book_value_equity": forecast.opening_book_value_equity,
            "cost_of_equity": cost_of_equity,
            "terminal_growth": forecast.terminal_growth.growth_rate,
            "shares_outstanding": shares_outstanding,
        },
        "explicit_abnormal_earnings": [
            {
                "year": row["period"],
                "abnormal_earnings": round(row["value"], 2),
                "present_value": round(row["present_value"], 2),
            }
            for row in details["explicit_abnormal_forecast"]
        ],
        "terminal_present_value": round(details["terminal_present_value"], 2),
        "equity_value": round(result["value"], 2),
        "value_per_share": round(details["value_per_share"], 2),
    }
    print(json.dumps(public_summary, indent=2))


if __name__ == "__main__":
    main()
