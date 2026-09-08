"""Execute an A-only research target through RQAlpha's corporate-action ledger.

This adapter never promotes a research factor to a confirmed strategy.
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]


def active_symbols(chosen: pd.Series, positions: object) -> list[str]:
    """Select desired or actually held names without touching future IPO instruments.

    Args:
        chosen: Previous-close nonnegative desired weights.
        positions: RQAlpha position mapping; iteration only visits existing records.
    Returns:
        list[str]: Sorted union; zero-target never-held symbols are not queried.
    """
    held = {symbol for symbol in positions if positions[symbol].quantity > 0}
    return sorted(set(chosen[chosen > 0].index) | held)


def run_target(target, output, initial_cash=1_000_000., holding_days=5):
    """Execute a validated target matrix through the optional RQAlpha adapter.

    Args:
        target: Chronological nonnegative target weights indexed by trading date.
        output: Empty directory receiving execution artifacts.
        initial_cash: Starting cash in the simulated account.
        holding_days: Rebalance interval measured in trading sessions.
    Returns:
        dict: Execution report written alongside the simulator artifacts.
    Raises:
        ModuleNotFoundError: If the optional RQAlpha backtest stack is unavailable.
    """
    try:
        import rqalpha
        from rqalpha.api import order_target_percent, subscribe_event, update_universe
        from rqalpha.const import ORDER_STATUS
        from rqalpha.core.events import EVENT
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "RQAlpha backtest extras are required for run_target; install the project backtest extra"
        ) from exc
    if target.empty or not isinstance(target.index,pd.DatetimeIndex):
        raise ValueError("Nonempty dated targets required")
    if target.index.has_duplicates or not target.index.is_monotonic_increasing:
        raise ValueError("Target dates must be unique and chronological")
    if target.index.min()<pd.Timestamp("2016-07-01") or target.index.max()>pd.Timestamp("2022-06-30"):
        raise ValueError("Research execution is restricted to A; B/H remain unread")
    values=target.to_numpy()
    if np.isinf(values).any() or np.nanmin(values)<0 or (target.sum(axis=1)>.95+1e-10).any():
        raise ValueError("Nonnegative targets with at least five percent cash required")
    output=Path(output)
    output.mkdir(parents=True,exist_ok=False)
    target.to_parquet(output/"target.parquet")
    daily,orders=[],[]
    signal_dates=[]
    def on_rejection(event):
        raise RuntimeError("RQAlpha rejected an execution order")
    def init(context):
        update_universe([])
        subscribe_event(EVENT.ORDER_CREATION_REJECT,on_rejection)
    def before_trading(context):
        """Subscribe only current targets and holdings; the input context is pre-open."""
        day = pd.Timestamp(context.now.date())
        if day not in target.index:
            raise RuntimeError("Missing target calendar day")
        index = target.index.get_loc(day)
        chosen = target.iloc[max(0, index-1)].fillna(0.) if index else target.iloc[0]*0
        update_universe(active_symbols(chosen, context.portfolio.positions))

    def open_auction(context,bars):
        day=pd.Timestamp(context.now.date())
        if day not in target.index:
            raise RuntimeError("Missing target calendar day")
        index=target.index.get_loc(day)
        if index==0 or (index-1)%holding_days:
            return
        signal_day=target.index[index-1]
        if signal_day>=day:
            raise AssertionError("Signal must precede execution")
        chosen=target.iloc[index-1].fillna(0.)
        signal_dates.append({"execution_date":str(day.date()),"signal_date":str(signal_day.date())})
        # Sell reductions first, leaving the fixed cash reserve for costs.
        needed = active_symbols(chosen, context.portfolio.positions)
        current={symbol:float(context.portfolio.positions[symbol].market_value)/
                 context.portfolio.total_value for symbol in needed}
        symbols=sorted(needed,key=lambda s:(chosen.get(s, 0.)-current[s],s))
        for symbol in symbols:
            desired=float(chosen.get(symbol, 0.))
            price=float(bars[symbol].open)
            delta=abs(desired-current[symbol])*context.portfolio.total_value
            if delta==0: continue
            if not np.isfinite(price) or price<=0:
                raise RuntimeError(f"Missing execution price: {day.date()} {symbol}")
            order=order_target_percent(symbol,desired)
            if order is None:
                # Less than one round lot can legitimately produce no order.
                if delta>=price*100:
                    raise RuntimeError(f"Requested target did not produce an order: {day.date()} {symbol}")
                continue
            orders.append(order)
    def after_trading(context):
        unresolved=[o for o in orders if o.status != ORDER_STATUS.FILLED]
        if unresolved:
            details=[{"symbol":o.order_book_id,"status":str(o.status),"quantity":o.quantity,
                      "filled":o.filled_quantity,"reason":o.message} for o in unresolved]
            (output/"unfilled-orders.json").write_text(json.dumps(details,indent=2))
            raise RuntimeError("Partial, cancelled or unfilled order invalidates this execution run")
        orders.clear()
        daily.append({"date":str(context.now.date()),"cash":float(context.portfolio.cash),
                      "total_value":float(context.portfolio.total_value)})
    config={
        "base":{"start_date":str(target.index[0].date()),"end_date":str(target.index[-1].date()),
                "frequency":"1d","accounts":{"stock":initial_cash},"rqdatac_uri":"disabled","capital_gain_tax_rate":0},
        "extra":{"log_level":"error"},
        "mod":{"local_rqdata":{"enabled":True,"lib":"rqalpha_mod_local_rqdata","priority":40,
                              "warehouse_path":str(ROOT/"artifacts/backtest/exploration.duckdb")},
               "sys_simulation":{"matching_type":"current_bar","price_limit":True,"volume_limit":True,
                                 "volume_percent":.1,"slippage":.0005},
               "sys_transaction_cost":{"stock_min_commission":5,"stock_commission_multiplier":1,
                                       "tax_multiplier":1,"pit_tax":True},
               "sys_analyser":{"enabled":True,"benchmark":None,"plot":False,
                               "output_file":str(output/"result.pkl")}}}
    (output/"config.json").write_text(json.dumps(config,indent=2))
    try:
        result=rqalpha.run_func(config=config,init=init,before_trading=before_trading,open_auction=open_auction,after_trading=after_trading)
        if result is None or "sys_analyser" not in result: raise RuntimeError("RQAlpha produced no result")
        trades=result["sys_analyser"]["trades"]
        trades.to_parquet(output/"trades.parquet")
        pd.DataFrame(daily).to_parquet(output/"daily-cash.parquet")
        report={"state":"EXECUTED_RESEARCH_ONLY","formal":False,"B_H_read":False,"trades":len(trades),
                "signal_dates":signal_dates,"rqalpha":rqalpha.__version__,
                "scope":"T+1 open execution with RQAlpha corporate actions; not independent factor validation"}
        (output/"execution.json").write_text(json.dumps(report,indent=2))
        return report
    except BaseException as exc:
        (output/"failure.json").write_text(json.dumps({"state":"INVALID_EXECUTION","type":type(exc).__name__,
            "reason":str(exc),"formal":False,"B_H_read":False},indent=2))
        raise


def from_research_factor(path,start,end,max_positions=20):
    """Fixed top-rank long-only projection, no outcome-based optimization."""
    signal=pd.read_parquet(path).loc[start:end]
    target=pd.DataFrame(0.,index=signal.index,columns=signal.columns)
    for date,row in signal.iterrows():
        selected=row.dropna().sort_values(ascending=False,kind="stable").head(max_positions).index
        if len(selected): target.loc[date,selected]=min(.05,.95/len(selected))
    return target.loc[:,target.gt(0).any()]


if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--factor",type=Path,required=True)
    p.add_argument("--start",required=True)
    p.add_argument("--end",required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    print(run_target(from_research_factor(a.factor,a.start,a.end),a.output))
