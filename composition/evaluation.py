"""组合成本评估：从合并后的每日目标重算转移量、固定成本和开盘至开盘研究收益。

目标权重转移是可复现的成本代理，不是漂移后真实成交额。实际成交、税费和公司行为
必须由独立 RQAlpha 回放验证；持有资产缺收益时不填零、不拼接伪造完整净值。
"""

from typing import Any

import numpy as np
import pandas as pd

from composition.core import CompositionConfig, validate_frame


def evaluate_targets(target: pd.DataFrame, forward_returns: pd.DataFrame,
                     config: CompositionConfig) -> tuple[pd.DataFrame, dict[str, Any]]:
    """评估冻结目标的研究收益与成本。

    Args:
        target: t 日决策、t+1 开盘执行的非负目标权重。
        forward_returns: t+1 开盘到 t+2 开盘的调整价格收益，与 target 同索引。
        config: 冻结固定成本；不在此优化权重和交易频率。
    Returns:
        tuple: 每日研究数据与总结；持仓缺收益则完整净值和回报统计为 None。
    """
    validate_frame(target, "target")
    validate_frame(forward_returns, "returns")
    if not target.index.equals(forward_returns.index) or not target.columns.equals(forward_returns.columns):
        raise ValueError("组合目标与收益必须完全对齐")
    if target.isna().any().any() or (target < 0).any().any() or target.sum(axis=1).gt(1 - config.min_cash + 1e-9).any():
        raise ValueError("组合目标违反多头/现金约束")
    changes = target - target.shift(1, fill_value=0.)
    buys = changes.clip(lower=0).sum(axis=1)
    sells = -changes.clip(upper=0).sum(axis=1)
    # 组合结束的清仓成本单独计入最后一行；不把剩余持仓当作已免费平仓。
    sells.iloc[-1] += target.iloc[-1].sum()
    cost = (buys + sells) * (config.commission_bp + config.slippage_bp) / 10000
    cost += sells * config.stamp_tax_bp / 10000
    missing = (target > 0) & forward_returns.isna()
    gross = (target * forward_returns.fillna(0)).sum(axis=1).mask(missing.any(axis=1))
    if (forward_returns.where(target > 0) < -1).any().any():
        raise ValueError("持有资产价格收益不能低于 -100%")
    net = gross - cost
    valid = not missing.any().any()
    if valid and (net <= -1).any():
        raise ValueError("固定成本模型出现净值归零，不能继续复合")
    daily = pd.DataFrame({"gross_return": gross, "net_return": net, "buy_weight": buys,
        "sell_weight": sells, "turnover_proxy": buys + sells, "cost_proxy": cost,
        "missing_held_returns": missing.sum(axis=1), "exposure": target.sum(axis=1)})
    daily["research_nav"] = (1 + net).cumprod() if valid else np.nan
    nav = daily.research_nav
    drawdown = nav / nav.cummax().clip(lower=1.) - 1 if valid else None
    report = {"state": "RESEARCH_ESTIMATE" if valid else "INVALID_RETURN_COVERAGE", "formal": False,
        "dates": len(target), "mean_daily_target_transfer": float((buys+sells).mean()),
        "sum_cost_proxy": float(cost.sum()), "mean_daily_cost_proxy": float(cost.mean()),
        "missing_held_returns": int(missing.sum().sum()), "incomplete_dates": int(missing.any(axis=1).sum()),
        "mean_gross_return": float(gross.mean()) if valid else None,
        "mean_net_return": float(net.mean()) if valid else None,
        "research_total_return": float(nav.iloc[-1] - 1) if valid else None,
        "research_max_drawdown": float(drawdown.min()) if valid else None,
        "mean_exposure": float(target.sum(axis=1).mean()),
        "execution_verified": False,
        "scope": "A-only adjusted-open research estimate; fixed target-transfer costs, no intraday fills, tax timing or inventory drift"}
    return daily, report


def transfer_comparison(component_targets: dict[str, pd.DataFrame], combined: pd.DataFrame,
                        config: CompositionConfig) -> dict[str, float | str]:
    """比较先交易后相加与先相加后交易的目标转移成本。

    Args:
        component_targets: 每个独立成分的完整资本目标。
        combined: 门控后的组合目标。
        config: 同一套固定成本。
    Returns:
        dict: 独立账户等分资本与合并账户的转移成本代理，允许组合成本更高。
    """
    if not component_targets:
        raise ValueError("缺少成分目标")
    costs, turnover = [], []
    for frame in component_targets.values():
        if not frame.index.equals(combined.index) or not frame.columns.equals(combined.columns):
            raise ValueError("成本比较的目标未对齐")
        delta = frame - frame.shift(1, fill_value=0.)
        buy, sell = float(delta.clip(lower=0).sum().sum()), float(-delta.clip(upper=0).sum().sum() + frame.iloc[-1].sum())
        turnover.append(buy + sell)
        costs.append(((buy+sell)*(config.commission_bp+config.slippage_bp)+sell*config.stamp_tax_bp)/10000)
    delta = combined - combined.shift(1, fill_value=0.)
    buy, sell = float(delta.clip(lower=0).sum().sum()), float(-delta.clip(upper=0).sum().sum() + combined.iloc[-1].sum())
    cost = ((buy+sell)*(config.commission_bp+config.slippage_bp)+sell*config.stamp_tax_bp)/10000
    return {"component_equal_capital_transfer": float(np.mean(turnover)),
        "combined_transfer": buy+sell, "component_equal_capital_cost": float(np.mean(costs)),
        "combined_cost": cost, "cost_difference": cost-float(np.mean(costs)),
        "scope": "Same signal dates and fixed target-transfer proxy; not real drift-adjusted executions"}