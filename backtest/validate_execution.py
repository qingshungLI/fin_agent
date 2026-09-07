"""Actual RQAlpha local-data event checks, entirely inside exploration dates."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import rqalpha
from rqalpha.api import order_shares, update_universe

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT / "artifacts/backtest/dividend-2018"
    out.mkdir(parents=True, exist_ok=True)
    positions = []
    def init(context):
        context.ordered = False
        update_universe(["000001.XSHE"])
    def open_auction(context, bars):
        if not context.ordered:
            order = order_shares("000001.XSHE", 1000)
            if order is None:
                raise RuntimeError("Smoke buy rejected")
            context.ordered = True
    def after_trading(context):
        positions.append({"date": str(context.now.date()), "cash": float(context.portfolio.cash),
                          "total_value": float(context.portfolio.total_value),
                          "shares": int(context.portfolio.positions["000001.XSHE"].quantity)})
    config = {
        "base": {"start_date": "2018-07-10", "end_date": "2018-07-16",
                 "frequency": "1d", "accounts": {"stock": 100000},
                 "rqdatac_uri": "disabled", "capital_gain_tax_rate": 0},
        "extra": {"log_level": "error"},
        "mod": {
            "local_rqdata": {"enabled": True, "lib": "rqalpha_mod_local_rqdata",
                            "priority": 40, "warehouse_path": str(ROOT / "artifacts/backtest/exploration.duckdb")},
            "sys_simulation": {"matching_type": "current_bar", "price_limit": True,
                               "volume_limit": True, "volume_percent": .1, "slippage": .0005},
            "sys_transaction_cost": {"stock_min_commission": 5, "stock_commission_multiplier": 1,
                                     "tax_multiplier": 1, "pit_tax": True},
            "sys_analyser": {"enabled": True, "benchmark": None, "plot": False,
                             "output_file": str(out / "result.pkl")},
        },
    }
    result = rqalpha.run_func(config=config, init=init, open_auction=open_auction, after_trading=after_trading)
    if result is None or "sys_analyser" not in result:
        raise RuntimeError("RQAlpha did not produce an analyser result")
    analysed = result["sys_analyser"]
    trades = analysed["trades"]
    if trades.empty:
        raise AssertionError("No actual trade")
    daily = pd.DataFrame(positions).set_index("date")
    expected = daily.loc["2018-07-11", "shares"] * 1.36 / 10
    actual = daily.loc["2018-07-12", "cash"] - daily.loc["2018-07-11", "cash"]
    assert np.isclose(actual, expected), (actual, expected)
    checks = {"passed": True, "rqalpha": rqalpha.__version__, "trades": len(trades),
              "dividend_expected": float(expected), "dividend_cash_delta": float(actual),
              "period": ["2018-07-10", "2018-07-16"], "B_H_read": False,
              "scope": "single-stock open-auction buy and cash dividend; not factor performance"}
    (out / "config.json").write_text(json.dumps(config,indent=2))
    (out / "checks.json").write_text(json.dumps(checks,indent=2))
    daily.to_parquet(out / "daily-cash.parquet")
    trades.to_parquet(out / "trades.parquet")
    print(checks, flush=True)


if __name__ == "__main__":
    main()
