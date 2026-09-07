"""测量管线：日截面相关和分组收益形成序列，时间块 bootstrap/HAC 估计不确定性。

影响分解同时保留中心化 psi 与可加贡献 Psi。所有推断以交易日为采样单位，缺失不填零。
"""

from typing import Any

import numpy as np
import pandas as pd

from engine.config import HORIZONS, ResearchConfig
from engine.data import MarketPanel
from engine.dsl import evaluate


def daily_ic(factor: pd.DataFrame, returns: pd.DataFrame, minimum: int = 30, rank: bool = False) -> pd.Series:
    """计算每日 Pearson 或秩相关；输入对齐矩阵，返回日序列，并列秩使用平均排名。"""
    if not factor.index.equals(returns.index) or not factor.columns.equals(returns.columns):
        raise ValueError("因子与收益索引不一致")
    valid = factor.notna() & returns.notna()
    x, y = factor.where(valid), returns.where(valid)
    if rank:
        x, y = x.rank(axis=1), y.rank(axis=1)
    x, y = x.sub(x.mean(axis=1), axis=0), y.sub(y.mean(axis=1), axis=0)
    denominator = (x.pow(2).sum(axis=1) * y.pow(2).sum(axis=1)).pow(0.5)
    return ((x * y).sum(axis=1) / denominator.replace(0, np.nan)).where(valid.sum(axis=1) >= minimum)


def block_means(values: np.ndarray, horizon: int, n_boot: int, seed: int) -> np.ndarray:
    """重抽连续日期块的均值；输入含缺失的日序列，返回 bootstrap 均值，不压缩日期。"""
    x = np.asarray(values, dtype=float)
    block = max(10, 2 * horizon)
    if x.ndim != 1 or len(x) < 2 * block or np.isfinite(x).sum() < block:
        raise ValueError("不足两个时间块，无法估计不确定性")
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(x) - block + 1, size=(n_boot, int(np.ceil(len(x) / block))))
    indices = (starts[..., None] + np.arange(block)).reshape(n_boot, -1)[:, :len(x)]
    samples = x[indices]
    count = np.isfinite(samples).sum(axis=1)
    if (count == 0).any():
        raise ValueError("bootstrap 出现全缺失时间块样本")
    return np.nansum(samples, axis=1) / count


def summarize(series: pd.Series, horizon: int, config: ResearchConfig) -> dict[str, Any]:
    """汇总日序列均值、HAC 与块不确定性；返回 JSON 指标，功效不足保留缺失。"""
    valid = series.dropna()
    base = {"mean": None, "se": None, "n_eff": None, "mde": None, "t": None,
            "p": 1.0, "p_negative": 1.0, "ci_low": None, "ci_high": None,
            "days": len(valid), "positive_fraction": None, "std": None,
            "q05": None, "q95": None, "skew": None}
    if len(valid) < max(20, 2 * max(10, 2 * horizon)):
        return base
    samples = block_means(series.to_numpy(), horizon, config.n_boot, config.seed)
    se = float(np.std(samples, ddof=1))
    mean = float(valid.mean())
    if not np.isfinite(se) or se <= np.finfo(float).eps:
        return {**base, "mean": mean, "reason": "序列方差退化，不能声称无限证据"}
    centered = series.to_numpy(dtype=float) - mean
    finite_count = np.isfinite(centered).sum()
    hac_var = float(np.nansum(centered ** 2) / finite_count)
    lag = max(horizon, int(4 * (len(series) / 100) ** (2 / 9)))
    for k in range(1, min(lag, len(series) - 1) + 1):
        hac_var += 2 * (1 - k / (lag + 1)) * float(np.nansum(centered[k:] * centered[:-k]) / finite_count)
    hac_se = float(np.sqrt(max(0, hac_var) / finite_count))
    error = samples - samples.mean()
    p = float((1 + np.count_nonzero(error >= mean)) / (config.n_boot + 1))
    p_negative = float((1 + np.count_nonzero(error <= mean)) / (config.n_boot + 1))
    # 百分位区间与检验均保留自相关块结构；HAC t 作为独立的诊断列。
    ci_low, ci_high = np.quantile(samples, [0.025, 0.975])
    return {**base, "mean": mean, "se": se, "n_eff": 1 / se ** 2, "mde": 2.8016 * se,
            "t": mean / hac_se if hac_se > 0 else None, "hac_se": hac_se, "hac_lag": lag,
            "p": p, "p_negative": p_negative, "ci_low": float(ci_low), "ci_high": float(ci_high),
            "positive_fraction": float((valid > 0).mean()), "std": float(valid.std()),
            "q05": float(valid.quantile(0.05)), "q95": float(valid.quantile(0.95)),
            "skew": float(valid.skew()) if valid.nunique() > 2 else 0.0}


def influence_decomposition(
    factor: pd.DataFrame, returns: pd.DataFrame, minimum: int = 100,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """返回中心化 psi 与可加 Psi；输入对齐矩阵，Psi 全局和等于有效日期平均 IC。"""
    valid = factor.notna() & returns.notna()
    valid.loc[valid.sum(axis=1) < minimum] = False
    x, y = factor.where(valid), returns.where(valid)
    x = x.sub(x.mean(axis=1), axis=0).div(x.std(axis=1, ddof=0).replace(0, np.nan), axis=0)
    y = y.sub(y.mean(axis=1), axis=0).div(y.std(axis=1, ddof=0).replace(0, np.nan), axis=0)
    rho = (x * y).mean(axis=1)
    psi = x * y - (x ** 2 + y ** 2).mul(rho / 2, axis=0)
    count = valid.sum(axis=1).replace(0, np.nan)
    contribution = psi.add(rho, axis=0).div(count * rho.notna().sum(), axis=0)
    if rho.notna().any() and not np.isclose(contribution.sum().sum(), rho.mean(), atol=1e-10):
        raise ArithmeticError("影响分解守恒校验失败")
    return psi, contribution


def group_returns(factor: pd.DataFrame, returns: pd.DataFrame, n_groups: int = 5) -> pd.DataFrame:
    """按日截面分位生成收益曲线；返回日期×组，重复值不强行打破并列。"""
    rank = factor.where(returns.notna()).rank(axis=1, pct=True, method="average")
    groups = np.minimum(np.ceil(rank * n_groups), n_groups)
    return pd.DataFrame({f"Q{i}": returns.where(groups == i).mean(axis=1) for i in range(1, n_groups + 1)})


def car_event(event: pd.DataFrame, daily_return: pd.DataFrame) -> list[dict[str, Any]]:
    """计算固定事件窗口的平均累计收益；返回 -10..20 曲线，越界或不完整窗口剔除。"""
    positions = np.argwhere(event.fillna(False).to_numpy(dtype=bool))
    array = daily_return.to_numpy(dtype=float)
    windows = []
    for day, stock in positions:
        if day < 10 or day + 20 >= len(array):
            continue
        window = array[day - 10:day + 21, stock]
        if np.isfinite(window).all():
            windows.append(np.cumprod(1 + window) - 1)
    if not windows:
        return []
    values = np.asarray(windows)
    return [{"offset": offset, "car": float(values[:, offset + 10].mean()), "events": len(values)}
            for offset in range(-10, 21)]


def measure_panel(
    structure: Any, panel: MarketPanel, config: ResearchConfig, cuts: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    """测量全部三表达式和四周期；返回报告及机器面板，状态判定由独立刀层负责。"""
    coverage = evaluate(structure.coverage, panel.fields, cuts).fillna(False).astype(bool)
    signals = [evaluate(expr, panel.fields, cuts).where(coverage) for expr in structure.operational]
    curves = []
    stored = {}
    for expression_index, signal in enumerate(signals):
        for horizon in HORIZONS:
            raw = panel.labels[f"raw_{horizon}"]
            residual = panel.labels[f"industry_resid_{horizon}"]
            ic = daily_ic(signal, residual, config.min_cross_section)
            raw_ic = daily_ic(signal, raw, config.min_cross_section)
            excess_ic = daily_ic(signal, panel.labels[f"market_excess_{horizon}"], config.min_cross_section)
            if not np.allclose(raw_ic, excess_ic, equal_nan=True, atol=1e-10):
                raise ArithmeticError("IC 平移不变性失败")
            groups = group_returns(signal, residual)
            summary = summarize(ic, horizon, config)
            curves.append({"expression": expression_index + 1, "horizon": horizon, **summary,
                           "raw_ic": float(raw_ic.mean()) if raw_ic.notna().any() else None,
                           "rank_ic": float(daily_ic(signal, residual, config.min_cross_section, True).mean()),
                           "tb": float((groups.Q5 - groups.Q1).mean()),
                           "groups": [float(groups[column].mean()) for column in groups]})
            stored[f"ic_e{expression_index + 1}_h{horizon}"] = ic.to_frame("ic")
            if expression_index == 0:
                stored[f"groups_h{horizon}"] = groups
    primary = signals[0]
    returns = panel.labels[f"industry_resid_{structure.primary_horizon}"]
    psi, contribution = influence_decomposition(primary, returns, minimum=max(100, config.min_cross_section))
    stored["psi"] = psi
    stored["contribution"] = contribution
    for i, signal in enumerate(signals):
        stored[f"signal_{i}"] = signal
    primary_ic = stored[f"ic_e1_h{structure.primary_horizon}"].ic
    monthly = []
    quarterly = []
    for period, sequence in primary_ic.groupby(primary_ic.index.to_period("M")):
        if sequence.notna().any():
            monthly.append({"date": str(period), "ic": float(sequence.mean()),
                            "low": float(sequence.quantile(0.05)), "high": float(sequence.quantile(0.95))})
    for period, sequence in primary_ic.groupby(primary_ic.index.to_period("Q")):
        quarterly.append({"period": str(period), **summarize(sequence, structure.primary_horizon, config)})
    absolute = contribution.abs().stack().sort_values(ascending=False)
    total = absolute.sum()
    concentration = {str(k): float(absolute.iloc[:max(1, int(len(absolute) * k / 100))].sum() / total)
                     if total > 0 else None for k in (5, 10, 20)}
    hit_valid = primary.notna() & returns.notna()
    hits = primary.gt(primary.median(axis=1), axis=0).eq(returns.gt(0)) & hit_valid
    return {"curves": curves, "monthly": monthly, "quarterly": quarterly,
            "concentration": concentration,
            "coverage": float((coverage & primary.notna()).sum().sum() / max(1, panel.fields["in_pool"].sum().sum())),
            "observations": int(hit_valid.sum().sum()), "dates": len(panel.dates),
            "hit_rate": float(hits.sum().sum() / max(1, hit_valid.sum().sum())),
            "car": car_event(panel.fields["failed_limit_up"], panel.fields["ret_1d"]),
            "contribution_sum": float(contribution.sum().sum()),
            "influence_valid_days": int(psi.notna().any(axis=1).sum())}, stored


def holm(p_values: list[float]) -> list[float]:
    """执行 Holm step-down；输入冻结批次 p 值，返回原顺序校正值，任意依赖下有效。"""
    values = np.asarray(p_values, dtype=float)
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError("p 值必须位于 [0,1]")
    order = np.argsort(values, kind="stable")
    adjusted = np.minimum(1, np.maximum.accumulate(values[order] * np.arange(len(values), 0, -1)))
    result = np.empty(len(values))
    result[order] = adjusted
    return result.tolist()


def power_budget(n_eff: float, explore_frac: float = 0.65, tau_main: float = 0.05) -> dict[str, float]:
    """预估确认侧功效；输入探索 n_eff/占比/效应，返回门槛，假设两段单位信息量相近。"""
    if n_eff <= 0 or not 0 < explore_frac < 1 or tau_main <= 0:
        raise ValueError("功效参数必须为正且探索占比位于 (0,1)")
    confirm_n = n_eff * (1 - explore_frac) / explore_frac
    return {"explore_n_eff": n_eff, "projected_confirm_n_eff": confirm_n,
            "main_mde": 2.8016 / np.sqrt(n_eff), "interaction_mde": 5.6032 / np.sqrt(confirm_n),
            "required_n_eff": (2.8016 / tau_main) ** 2}
