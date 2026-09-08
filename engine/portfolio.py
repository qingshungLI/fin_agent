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
    stamp_tax_bp: float = 10.0
    initial_cash: float = 1_000_000.0
    round_lot: int = 100

    def __post_init__(self) -> None:
        """验证冻结执行参数；无返回，所有金额/比例与持有期必须合法。"""
        if (self.initial_cash <= 0 or self.round_lot < 1 or self.max_positions < 1
                or self.holding_days < 1 or not 0 < self.max_weight <= 1
                or not 0 <= self.min_cash < 1 or not 0 < self.max_participation <= 1
                or min(self.commission_bp, self.slippage_bp, self.stamp_tax_bp) < 0):
            raise ValueError("执行配置中的资金、比例或周期无效")


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
    covered = pd.DataFrame(False, index=weights.index, columns=weights.columns)
    for offset in range(peak_horizon):
        shifted = weights.shift(offset)
        covered |= shifted.notna()
        output = output.add(shifted.fillna(0) * (1 - offset / peak_horizon), fill_value=0)
    return output.where(covered)


def assemble_portfolio(structures: list[dict[str, Any]], paths: list[pd.DataFrame]) -> dict[str, Any]:
    """按 NaN 忽略规则聚合结构路径；输入已通过结构及路径，返回组合与覆盖计数。"""
    if not paths:
        raise ValueError("没有通过确认的结构")
    aligned = [path.reindex_like(paths[0]) for path in paths]
    if len(structures) != len(paths) or any(
        item.get("verdict") != "PASS" or not item.get("formal") for item in structures
    ):
        raise ValueError("组合仅接收完成正式确认的 PASS 结构")
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
    if target.empty or len(target) <= config.holding_days + 1:
        raise ValueError("回测日期不足以完成一个冻结持有周期")
    if not target.index.is_monotonic_increasing or target.index.has_duplicates:
        raise ValueError("目标持仓日期必须严格递增且唯一")
    for name in required:
        if not bars[name].index.equals(target.index) or not bars[name].columns.equals(target.columns):
            raise ValueError(f"执行矩阵索引未对齐: {name}")
    if np.isinf(target.to_numpy()).any() or (target < 0).any().any():
        raise ValueError("多头目标不得含负权重或无穷值")
    # 有公司行为时必须由已对接的 RQAlpha 公司行为账本处理，不能将复权价格当成交价。
    adjustment = bars.get("adjustment")
    if adjustment is not None and adjustment.nunique().gt(1).any():
        raise ValueError("区间包含公司行为，必须接入 RQAlpha 现金分红/送转账本后执行")
    cash = config.initial_cash
    positions: dict[str, tuple[int, int]] = {}
    nav = pd.Series(1.0, index=target.index)
    trades: list[dict[str, Any]] = []
    for day_index in range(1, len(target)):
        day = target.index[day_index]
        opening = bars["open"].loc[day]
        daily_turnover, daily_fees = 0.0, 0.0
        due = {symbol: quantity for symbol, (quantity, exit_day) in positions.items() if exit_day <= day_index}
        for symbol, quantity in due.items():
            price = float(opening[symbol])
            limit = float(bars["limit_down"].loc[day, symbol])
            volume = float(bars["volume"].loc[day, symbol])
            if (not bars["not_suspended"].loc[day, symbol] or not np.isfinite(price)
                    or price <= 0 or not np.isfinite(limit) or price <= limit
                    or not np.isfinite(volume) or quantity > volume * config.max_participation):
                raise RuntimeError(f"到期卖出无法成交: {day.date()} {symbol} 数量={quantity}")
            gross = quantity * price * (1 - config.slippage_bp / 10000)
            fee = gross * (config.commission_bp + config.stamp_tax_bp) / 10000
            cash += gross - fee
            daily_fees += fee + quantity * price - gross
            daily_turnover += quantity * price
            trades.append({"date": str(day.date()), "symbol": symbol, "side": "sell",
                           "quantity": quantity, "price": price, "fee": fee})
            del positions[symbol]
        if (day_index - 1) % config.holding_days == 0 and day_index + config.holding_days < len(target):
            if positions:
                raise RuntimeError("冻结调仓日仍有未到期持仓，执行协议不一致")
            available = target.iloc[day_index - 1].dropna()
            selected = available[available > 0].sort_values(ascending=False, kind="stable").head(config.max_positions)
            weight = min(config.max_weight, (1 - config.min_cash) / max(1, len(selected)))
            budget_base = cash
            for symbol in selected.index:
                price = float(opening[symbol])
                limit = float(bars["limit_up"].loc[day, symbol])
                if (not bars["not_suspended"].loc[day, symbol] or not np.isfinite(price)
                        or price <= 0 or not np.isfinite(limit) or price >= limit):
                    raise RuntimeError(f"T+1 买入无法成交: {day.date()} {symbol}")
                fill_price = price * (1 + config.slippage_bp / 10000)
                quantity = int(budget_base * weight / (fill_price * (1 + config.commission_bp / 10000))
                               // config.round_lot) * config.round_lot
                volume = float(bars["volume"].loc[day, symbol])
                if not np.isfinite(volume) or quantity > volume * config.max_participation:
                    raise RuntimeError(f"成交量约束失败: {day.date()} {symbol} 数量={quantity}")
                if quantity == 0:
                    continue
                fee = quantity * fill_price * config.commission_bp / 10000
                cash -= quantity * fill_price + fee
                if cash < -1e-7:
                    raise ArithmeticError("现金透支")
                positions[symbol] = (quantity, day_index + config.holding_days)
                daily_turnover += quantity * price
                daily_fees += fee + quantity * (fill_price - price)
                trades.append({"date": str(day.date()), "symbol": symbol, "side": "buy",
                               "quantity": quantity, "price": fill_price, "fee": fee})
        value = cash
        for symbol, (quantity, _) in positions.items():
            close = float(bars["close"].loc[day, symbol])
            if not np.isfinite(close) or close <= 0:
                raise RuntimeError(f"持仓估值缺失: {day.date()} {symbol}")
            value += quantity * close
        nav.iloc[day_index] = value / config.initial_cash
        trades.append({"date": str(day.date()), "side": "summary", "turnover": daily_turnover / config.initial_cash,
                       "cost": daily_fees, "positions": len(positions), "cash": cash})
    daily = nav.pct_change(fill_method=None).dropna()
    sharpe = float(np.sqrt(252) * daily.mean() / daily.std()) if daily.std() > 0 else None
    drawdown = nav / nav.cummax() - 1
    return {"nav": {str(day.date()): float(value) for day, value in nav.items()},
            "cumulative_return": float(nav.iloc[-1] - 1),
            "sharpe": sharpe, "max_drawdown": float(drawdown.min()) if drawdown.notna().any() else None,
            "turnover": float(np.mean([item["turnover"] for item in trades if item["side"] == "summary"])),
            "failed_orders": 0, "trades": trades, "execution": config.__dict__}
