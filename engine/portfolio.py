"""交易管线：结构信号到目标持仓路径，再以 T+1 开盘执行；不可成交直接终止回测。"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ExecutionConfig:
    """冻结执行规则；输入持仓/现金/交易约束，禁止从历史峰值调参。"""
    max_positions: int = 50
    max_weight: float = 0.05
    min_cash: float = 0.05
    max_participation: float = 0.1
    holding_days: int = 5
    commission_bp: float = 3.0
    slippage_bp: float = 5.0
    stamp_tax_bp: float = 5.0


def continuous_weight(signal: pd.DataFrame, coverage: pd.DataFrame, sign: int = 1) -> pd.DataFrame:
    """将信号转为截面连续权重；输入信号/覆盖，覆盖外返回 NaN 而非 0。"""
    if sign not in (-1, 1):
        raise ValueError("方向必须为 ±1")
    rank = signal.rank(axis=1, pct=True)
    centered = (rank - 0.5) * 2 * sign
    return centered.where(coverage)


def position_path(weights: pd.DataFrame, peak_horizon: int) -> pd.DataFrame:
    """按冻结 horizon 展开线性衰减目标持仓；输入日权重和周期，返回日×股票路径。"""
    if peak_horizon not in (1, 3, 5, 10):
        raise ValueError("只支持登记的 horizon")
    output = pd.DataFrame(0.0, index=weights.index, columns=weights.columns)
    for offset in range(peak_horizon):
        output = output.add(weights.shift(offset).fillna(0) * (1 - offset / peak_horizon), fill_value=0)
    return output


def assemble_portfolio(structures: list[dict[str, Any]], paths: list[pd.DataFrame]) -> dict[str, Any]:
    """按 NaN 忽略规则聚合结构路径；输入已通过结构及路径，返回组合与覆盖计数。"""
    if not paths:
        raise ValueError("没有通过确认的结构")
    aligned = [path.reindex_like(paths[0]) for path in paths]
    combined = pd.concat(aligned).groupby(level=0).mean() if len(aligned) > 1 else aligned[0]
    count = pd.concat([path.notna().astype(int) for path in aligned]).groupby(level=0).sum()
    combined = combined.where(count > 0)
    combined = combined.div(combined.abs().sum(axis=1).replace(0, np.nan), axis=0)
    return {"target": combined, "coverage_count": count, "structures": [item["id"] for item in structures]}


def execute_long_only(
    target: pd.DataFrame, bars: dict[str, pd.DataFrame], config: ExecutionConfig,
) -> dict[str, Any]:
    """执行 T+1 开盘多头回测；输入目标/行情矩阵，无法成交抛出带上下文异常。"""
    required = {"open", "close", "volume", "total_turnover", "not_suspended", "limit_up", "limit_down"}
    if not required <= bars.keys():
        raise ValueError(f"缺少执行字段: {sorted(required - bars.keys())}")
    target = target.clip(lower=0).where(target > 0)
    holdings = pd.DataFrame(0.0, index=target.index, columns=target.columns)
    nav = pd.Series(np.nan, index=target.index)
    trades = []
    for day_index, day in enumerate(target.index[:-1]):
        next_day = target.index[day_index + 1]
        desired = target.loc[day].dropna().nlargest(config.max_positions)
        desired = desired.clip(upper=config.max_weight)
        desired = desired / max(desired.sum(), 1 - config.min_cash)
        prices = bars["open"].loc[next_day]
        can_trade = bars["not_suspended"].loc[next_day] & prices.gt(0) & prices.lt(bars["limit_up"].loc[next_day]) & prices.gt(bars["limit_down"].loc[next_day])
        unavailable = desired.index[~can_trade.reindex(desired.index).fillna(False)]
        if len(unavailable):
            raise RuntimeError(f"T+1 无法成交，日期={next_day.date()}，证券={unavailable.tolist()}")
        holdings.loc[next_day] = desired
        turnover = float((holdings.loc[next_day] - holdings.loc[day]).abs().sum())
        cost = turnover * (config.commission_bp + config.slippage_bp) / 10000
        close = bars["close"].loc[next_day]
        if (close <= 0).any():
            raise RuntimeError(f"收盘价非法，日期={next_day.date()}")
        ret = (close / prices - 1).where(holdings.loc[next_day].gt(0)).fillna(0)
        nav.loc[next_day] = (1 - cost + float((holdings.loc[next_day] * ret).sum())) * nav.loc[day] if pd.notna(nav.loc[day]) else (1 - cost + float((holdings.loc[next_day] * ret).sum()))
        trades.append({"date": str(next_day.date()), "turnover": turnover, "cost": cost, "positions": int((holdings.loc[next_day] > 0).sum())})
    daily = nav.pct_change().dropna()
    sharpe = float(np.sqrt(252) * daily.mean() / daily.std()) if daily.std() > 0 else None
    drawdown = nav / nav.cummax() - 1
    return {"nav": nav.dropna().to_dict(), "cumulative_return": float(nav.dropna().iloc[-1] - 1) if nav.notna().any() else None,
            "sharpe": sharpe, "max_drawdown": float(drawdown.min()) if drawdown.notna().any() else None,
            "turnover": float(np.mean([item["turnover"] for item in trades])) if trades else 0,
            "failed_orders": 0, "trades": trades, "execution": config.__dict__}
