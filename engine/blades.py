"""判别管线：先功效闸门，再安慰剂、断言、增量；确认批次另行执行正交矩和 Holm。

每把刀保留独立状态与后续动作。重复采样加一修正避免零 p；阶段 A 不产生正式 PASS。
"""

from typing import Any

import numpy as np
import pandas as pd

from engine.catalog import Structure
from engine.config import ResearchConfig
from engine.data import MarketPanel
from engine.metrics import daily_ic, group_returns, summarize


def _array_ic(x: np.ndarray, y: np.ndarray) -> float:
    """计算完整矩阵的平均日 Pearson IC；输入同形数组，返回均值，零方差日剔除。"""
    x = x - x.mean(axis=1, keepdims=True)
    y = y - y.mean(axis=1, keepdims=True)
    denominator = np.sqrt(np.sum(x * x, axis=1) * np.sum(y * y, axis=1))
    valid = denominator > 1e-15
    return float(np.mean(np.sum(x * y, axis=1)[valid] / denominator[valid])) if valid.any() else 0.0


def iaaft(values: np.ndarray, rng: np.random.Generator, iterations: int = 30) -> tuple[np.ndarray, float]:
    """逐股票生成 IAAFT 替代序列；输入完整时间×股票数组，返回替代值及功率谱相对误差。"""
    if not np.isfinite(values).all():
        raise ValueError("IAAFT 不接受缺失，必须使用已披露的完整连续子面板")
    sorted_values = np.sort(values, axis=0)
    amplitude = np.abs(np.fft.rfft(values, axis=0))
    surrogate = np.take_along_axis(values, np.argsort(rng.random(values.shape), axis=0), axis=0)
    for _ in range(iterations):
        phase = np.angle(np.fft.rfft(surrogate, axis=0))
        filtered = np.fft.irfft(amplitude * np.exp(1j * phase), n=len(values), axis=0)
        order = np.argsort(filtered, axis=0)
        surrogate = np.empty_like(filtered)
        np.put_along_axis(surrogate, order, sorted_values, axis=0)
    error = np.linalg.norm(np.abs(np.fft.rfft(surrogate, axis=0)) - amplitude) / max(np.linalg.norm(amplitude), 1e-12)
    return surrogate, float(error)


def blade_placebo(signal, returns, config, horizon=5, eligibility=None):
    """Full daily eligible universe; no fixed or complete-security sample."""
    from engine.placebo import full_market_placebo
    return full_market_placebo(signal, returns, config, horizon, eligibility)


def _assertion_state(summary: dict[str, Any], tolerance: float = 0) -> str:
    """由置信区间产生三态；输入方向统一的统计摘要，返回 hold/violated/untested。"""
    if summary["ci_low"] is None:
        return "untested"
    if summary["ci_low"] > tolerance:
        return "hold"
    if summary["ci_high"] < -tolerance:
        return "violated"
    return "untested"


def blade_assertion(
    structure: Structure, panel: MarketPanel, measured: dict[str, pd.DataFrame],
    config: ResearchConfig,
) -> list[dict[str, Any]]:
    """Return support p-values for the entire necessary-assertion hypothesis.

    Intersections use max(p); unions use a Bonferroni bound. This lets frozen-batch
    Holm control false mechanism claims even when their main effects are real.
    """
    signal = measured["signal_0"]
    result = []

    def directional(sequence, horizon, tolerance):
        summary = summarize(sequence - tolerance, horizon, config)
        negative = summarize(-sequence - tolerance, horizon, config) if tolerance else None
        return summary, summary["p"], negative["p"] if negative else summary["p_negative"]

    for assertion in structure.assertions:
        horizon = assertion.horizons[0]
        returns = panel.labels[f"industry_resid_{horizon}"]
        support, contradiction = 1.0, 1.0
        if assertion.kind == "sign":
            tests = [directional(measured[f"ic_e{i}_h{horizon}"].ic * assertion.direction,
                                 horizon, assertion.tolerance) for i in (1, 2, 3)]
            support = max(t[1] for t in tests)
            contradiction = min(1., 3 * min(t[2] for t in tests))
            detail = {"expressions": [t[0] for t in tests]}
        elif assertion.kind == "shape":
            groups = group_returns(signal, returns)
            direction = 1 if assertion.relation == "monotone_up" else -1
            tests = [directional((groups.iloc[:, i+1] - groups.iloc[:, i]) * direction,
                                 horizon, assertion.tolerance) for i in range(groups.shape[1]-1)]
            support = max(t[1] for t in tests)
            contradiction = min(1., len(tests) * min(t[2] for t in tests))
            detail = {"adjacent_differences": [t[0] for t in tests],
                      "hypothesis": "all adjacent dose differences have the frozen direction"}
        elif assertion.kind == "peak":
            low, high = assertion.peak_range
            inside = [h for h in (1,3,5,10) if low <= h <= high]
            outside = [h for h in (1,3,5,10) if h not in inside]
            comparisons = {}
            if inside and outside:
                for hi in inside:
                    for ho in outside:
                        comparisons[(hi,ho)] = directional(
                            measured[f"ic_e1_h{hi}"].ic - measured[f"ic_e1_h{ho}"].ic,
                            max(hi,ho), assertion.tolerance)
                # There exists an inside horizon beating every outside horizon.
                # The minimization is explicitly corrected; no selected winner p-value.
                support = min(1., len(inside) * min(
                    max(comparisons[(hi,ho)][1] for ho in outside) for hi in inside))
                contradiction = min(1., len(outside) * min(
                    max(comparisons[(hi,ho)][2] for hi in inside) for ho in outside))
            detail = {"comparisons": {f"{hi}_vs_{ho}": t[0] for (hi,ho),t in comparisons.items()},
                      "hypothesis": "maximum IC within frozen horizon interval exceeds maximum outside",
                      "selection_correction": "union bound over candidate winning horizons"}
        else:
            moderator = panel.fields.get(assertion.subject)
            if moderator is None:
                detail = {"reason": f"缺少旁证字段 {assertion.subject}"}
            else:
                if assertion.subject == structure.lineage.get("moderator") and "ungated_signal" in measured:
                    source_signal = measured["ungated_signal"]
                    threshold = float(measured["condition_cut"].value.iloc[0])
                    high_mask, low_mask = moderator > threshold, moderator <= threshold
                else:
                    source_signal = signal
                    high_mask, low_mask = moderator >= 70, moderator <= 30
                high_ic = daily_ic(source_signal.where(high_mask), returns, config.min_cross_section)
                low_ic = daily_ic(source_signal.where(low_mask), returns, config.min_cross_section)
                detail, support, contradiction = directional((high_ic-low_ic) * assertion.direction,
                                                             horizon, assertion.tolerance)
        state = "hold" if support < .025 else "violated" if contradiction < .025 else "untested"
        result.append({"id": assertion.id, "kind": assertion.kind, "subject": assertion.subject,
                       "state": state, "p_support": support, "p_contradiction": contradiction,
                       "detail": detail, "attribution": assertion.attribution})
    return result


def blade_increment(
    signal: pd.DataFrame, returns: pd.DataFrame, library: list[pd.DataFrame],
    horizon: int, config: ResearchConfig,
) -> dict[str, Any]:
    """对重叠超过 20% 的已登记信号残差化；返回残差 IC，新库为空时明确不适用。"""
    peers = []
    for other in library:
        common = (signal.notna() & other.notna()).sum().sum()
        if common / max(1, signal.notna().sum().sum()) > 0.2:
            peers.append(other.reindex_like(signal))
    if not peers:
        return {"state": "not_applicable", "reason": "尚无重叠的已验证结构", "peers": 0}
    residual = pd.DataFrame(np.nan, index=signal.index, columns=signal.columns)
    for day in range(len(signal)):
        target = signal.iloc[day].to_numpy()
        design = np.column_stack([np.ones(len(target)), *[peer.iloc[day].to_numpy() for peer in peers]])
        valid = np.isfinite(target) & np.isfinite(design).all(axis=1)
        if valid.sum() <= design.shape[1] + config.min_cross_section:
            continue
        coefficients = np.linalg.lstsq(design[valid], target[valid], rcond=None)[0]
        residual.iloc[day, np.flatnonzero(valid)] = target[valid] - design[valid] @ coefficients
    summary = summarize(daily_ic(residual, returns, config.min_cross_section), horizon, config)
    state = "pass" if _assertion_state(summary) == "hold" else "untested"
    return {"state": state, "peers": len(peers), "residual": summary}


def run_blades(
    structure: Structure, panel: MarketPanel, measurement: dict[str, Any],
    stored: dict[str, pd.DataFrame], library: list[pd.DataFrame], config: ResearchConfig,
) -> dict[str, Any]:
    """短路执行 A 段前三把刀；返回临时三态与原因，不在探索段授予 PASS。"""
    primary = next(row for row in measurement["curves"] if row["expression"] == 1 and row["horizon"] == structure.primary_horizon)
    base = {"verdict": "UNDECIDABLE", "formal": False, "assertions": [],
            "placebo": {"state": "untested"}, "increment": {"state": "untested"}, "icm": None}
    if primary["days"] < config.min_dates or (config.mode != "fast" and
            (primary["mde"] is None or primary["mde"] > config.min_effect)):
        return {**base, "reason": "有效样本不足以在 80% 功效下检出事前最小效应", "gate": "closed"}
    placebo = blade_placebo(stored["signal_0"],
                             panel.labels[f"industry_resid_{structure.primary_horizon}"],
                             config, structure.primary_horizon, eligibility=panel.fields["in_pool"] & panel.fields["not_st"])
    if placebo["state"] != "pass" and config.mode != "fast":
        return {**base, "placebo": placebo, "gate": "open", "reason": "安慰剂未通过；停止机制解读，回查度量与时序伪影"}
    assertions = blade_assertion(structure, panel, stored, config)
    increment = blade_increment(stored["signal_0"], panel.labels[f"industry_resid_{structure.primary_horizon}"],
                                library, structure.primary_horizon, config)
    violated = any(row["state"] == "violated" for row in assertions)
    return {**base, "gate": "open", "placebo": placebo, "assertions": assertions, "increment": increment,
            "verdict": "FAIL" if violated else "UNDECIDABLE",
            "reason": "存在明确反向断言；保留效应、重新登记机制" if violated else "探索完成；正式结论等待冻结批次确认"}
