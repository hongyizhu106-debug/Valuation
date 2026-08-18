from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402


def main() -> None:
    """Run a simple PE-implied earnings-benchmark net-income path example."""

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    pe = 12.0
    net_income_ttm = 100.0
    book_value_equity = 900.0
    market_value = pe * net_income_ttm
    cost_of_equity = 0.10
    terminal_growth = 0.035
    rho = 0.75

    initial_spread, path, terminal = app.solve_pe_implied_earnings_benchmark_model(
        market_value=market_value,
        net_income_ttm=net_income_ttm,
        book_equity=book_value_equity,
        buyback_base=20.0,
        dividend_ttm=10.0,
        equity_cost=cost_of_equity,
        terminal_growth=terminal_growth,
        buyback_growth=terminal_growth,
        dividend_growth=0.02,
        fade_rho=rho,
        forecast_years=5,
        extension_years=5,
    )
    if initial_spread is None or not path or terminal is None:
        raise RuntimeError("PE-implied earnings-benchmark model did not converge.")

    result = {
        "model": "基于收益基准的 PE 隐含净利润路径模型",
        "formula": "MV_PE = PE * NI_0; 收益_NI_t = re * BVE_(t-1); NI_t = (re + spread_t) * BVE_(t-1)",
        "assumptions": {
            "pe": pe,
            "net_income_ttm": net_income_ttm,
            "market_value_pe": market_value,
            "opening_book_value_equity": book_value_equity,
            "cost_of_equity": cost_of_equity,
            "rho": rho,
            "terminal_growth": terminal_growth,
        },
        "solved_initial_spread": round(initial_spread, 4),
        "first_three_years": [
            {
                "year": int(row["year"]),
                "beginning_book_value": round(row["beginning_book_value"], 2),
                "earnings_benchmark_ni": round(cost_of_equity * row["beginning_book_value"], 2),
                "implied_net_income": round(row["net_income"], 2),
                "implied_ni_growth": round(row["net_income_growth"], 4),
                "ending_book_value": round(row["ending_book_value"], 2),
            }
            for row in path[:3]
        ],
        "model_value": round(terminal["model_value"], 2),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
