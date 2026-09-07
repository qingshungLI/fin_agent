"""证据管线：盲下注与已测试断言对账，计算校准和实验性 e 轨迹。

估计的 p0 使用双侧置信界；未测试断言保持财富 1 和原冻结权重。正式判定不消费此轨迹。
"""

from typing import Any

import numpy as np
from scipy import stats
from sklearn.linear_model import LogisticRegression


def estimate_p0(outcomes: list[bool], alpha: float = 0.05) -> dict[str, float]:
    """估计零分布命中率及 Clopper-Pearson 界；输入二元结果，返回点估计和区间。"""
    if not outcomes or not 0 < alpha < 1:
        raise ValueError("p0 需要非空安慰剂结果及合法 alpha")
    n, k = len(outcomes), int(sum(outcomes))
    return {"estimate": k / n,
            "lower": 0.0 if k == 0 else float(stats.beta.ppf(alpha / 2, k, n - k + 1)),
            "upper": 1.0 if k == n else float(stats.beta.ppf(1 - alpha / 2, k + 1, n - k))}


def shrink_bet(probability: float, lam: float = 0.5) -> float:
    """执行分数 Kelly 收缩；输入概率和历史斜率，返回收缩值，冷启动 lambda=0.5。"""
    if not 0 <= probability <= 1 or not 0 <= lam <= 1:
        raise ValueError("概率和收缩系数必须在 [0,1]")
    return 0.5 + lam * (probability - 0.5)


def bet_on_assertion(q: float, p0: dict[str, float], outcome: str) -> float:
    """计算保守实验性财富比；输入盲概率、p0 区间与三态，返回非负财富。"""
    if outcome == "untested":
        return 1.0
    if not 0 < q < 1 or not 0 <= p0["lower"] <= p0["upper"] <= 1:
        raise ValueError("下注概率或零概率区间不合法")
    if outcome == "hold":
        return q / max(p0["upper"], 1e-12)
    if outcome == "violated":
        return (1 - q) / max(1 - p0["lower"], 1e-12)
    raise ValueError("未知断言状态")


def calibrate_p_to_e(p: float) -> float:
    """用积分为 1 的校准族转换 p；返回实验性 e，要求 p>0 且来自有效检验。"""
    if not 0 < p <= 1:
        raise ValueError("p-to-e 要求 0<p<=1；Monte Carlo 必须使用加一修正")
    return p ** -0.5 - 1


def merge_e(values: list[float], weights: list[float], mode: str = "parallel") -> float:
    """合并冻结权重的 e；输入非负值，返回均值或独立实验乘积，不允许事后权重归一化。"""
    if not values or len(values) != len(weights) or min(values) < 0 or not np.isfinite(values).all():
        raise ValueError("e 列表和权重不合法")
    if min(weights) < 0 or not np.isclose(sum(weights), 1):
        raise ValueError("权重必须非负且事前合计为 1")
    if mode == "parallel":
        return float(np.dot(values, weights))
    if mode == "independent":
        return float(np.prod(values))
    raise ValueError("只允许同数据平均或独立实验相乘")


def calibration_report(probabilities: list[float], outcomes: list[int]) -> dict[str, Any]:
    """输出盲下注 Brier/对数损失与可靠性曲线；输入已测试配对，空数据返回明确状态。"""
    if len(probabilities) != len(outcomes):
        raise ValueError("概率和结果数量不同")
    if not probabilities:
        return {"state": "no_tested_assertions", "count": 0, "bins": []}
    q, y = np.asarray(probabilities), np.asarray(outcomes)
    if ((q <= 0) | (q >= 1)).any() or not np.isin(y, [0, 1]).all():
        raise ValueError("校准输入必须是 (0,1) 概率与二元结果")
    bins = []
    for lower in np.arange(0, 1, 0.1):
        mask = (q >= lower) & (q < lower + 0.1)
        if mask.any():
            bins.append({"predicted": float(q[mask].mean()), "observed": float(y[mask].mean()), "count": int(mask.sum())})
    return {"state": "measured", "count": len(q), "brier": float(np.mean((q - y) ** 2)),
            "log_loss": float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q))), "bins": bins}


def platt_calibrate(history_q: list[float], history_y: list[int], q: list[float]) -> list[float]:
    """仅用历史已结算概率做 Platt 校准；返回新概率，冷启动不虚构历史拟合。"""
    if len(history_q) < 30 or len(set(history_y)) < 2:
        return [shrink_bet(value) for value in q]
    logits = np.log(np.clip(history_q, 1e-5, 1 - 1e-5) / (1 - np.clip(history_q, 1e-5, 1 - 1e-5)))
    model = LogisticRegression().fit(logits.reshape(-1, 1), history_y)
    incoming = np.log(np.asarray(q) / (1 - np.asarray(q))).reshape(-1, 1)
    return [shrink_bet(float(value)) for value in model.predict_proba(incoming)[:, 1]]
