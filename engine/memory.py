"""记忆管线：季度效应与已知测量误差进入分阶段层次贝叶斯，输出诊断和下一探针。

后验只用于研究计划；样本共用造成的相关性必须披露，诊断失败返回 UNIDENTIFIABLE。
族和形式分开编码，四个语义槽位不作为可独立识别的因子。
"""

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats


def build_design_matrix(frame: pd.DataFrame, stage: str) -> tuple[np.ndarray, list[str]]:
    """生成有基准水平的设计矩阵；输入季度档案及阶段，返回矩阵/列名。"""
    if frame.empty or not {"family", "form", "period", "structure"} <= set(frame):
        raise ValueError("层次模型输入为空或缺少设计字段")
    terms = ["period"] if stage == "A" else ["period", "family", "form"]
    design = pd.get_dummies(frame[terms].astype(str), drop_first=True, dtype=float)
    if stage == "C":
        interaction = pd.get_dummies(frame.family.astype(str) + ":" + frame.form.astype(str), drop_first=True, dtype=float)
        design = pd.concat([design, interaction], axis=1)
    return np.column_stack([np.ones(len(frame)), design]), ["intercept", *design.columns]


def prior_overlap(samples: np.ndarray, prior: np.ndarray) -> float:
    """估计先验后验密度重叠积分；输入抽样向量，返回 [0,1]，退化分布不强行 KDE。"""
    if np.std(samples) <= 1e-12 or np.std(prior) <= 1e-12:
        return 1.0
    grid = np.linspace(min(np.quantile(samples, 0.001), np.quantile(prior, 0.001)),
                       max(np.quantile(samples, 0.999), np.quantile(prior, 0.999)), 250)
    return float(np.clip(np.trapz(np.minimum(stats.gaussian_kde(samples)(grid),
                                             stats.gaussian_kde(prior)(grid)), grid), 0, 1))


def fit_hierarchy(frame: pd.DataFrame, seed: int = 42, draws: int = 1000) -> dict[str, Any]:
    """拟合 HalfNormal 尺度层次模型；输入季度效应表，返回后验诊断，四链收敛后才解读。"""
    if frame.empty or frame.structure.nunique() < 2:
        return {"state": "UNIDENTIFIABLE", "reason": "至少需要两个不同结构", "terms": []}
    frame = frame.dropna(subset=["mean", "se"])
    frame = frame[frame.se > 0].copy()
    if len(frame) < 12:
        return {"state": "UNIDENTIFIABLE", "reason": "有效季度测量不足", "terms": []}
    count = frame.structure.nunique()
    stage = "A" if count < 10 else "B" if count <= 30 else "C"
    design, columns = build_design_matrix(frame, stage)
    rank = int(np.linalg.matrix_rank(design))
    if rank < design.shape[1]:
        return {"state": "UNIDENTIFIABLE", "reason": "族/形式设计矩阵欠秩，优先补充析因格",
                "rank": rank, "columns": len(columns), "terms": []}
    import pymc as pm
    import arviz as az

    categories = {key: sorted(frame[key].astype(str).unique()) for key in ("structure", "period", "family", "form")}
    encodings = {key: pd.Categorical(frame[key].astype(str), categories=values).codes for key, values in categories.items()}
    groups = ["period", "structure"] + (["family", "form"] if stage != "A" else [])
    if stage == "C":
        frame["interaction"] = frame.family.astype(str) + ":" + frame.form.astype(str)
        categories["interaction"] = sorted(frame.interaction.unique())
        encodings["interaction"] = pd.Categorical(frame.interaction, categories=categories["interaction"]).codes
        groups.append("interaction")
    with pm.Model(coords=categories):
        mu = pm.Normal("mu", 0, 0.05)
        predictor = mu
        for group in groups:
            scale = pm.HalfNormal("sigma_" + group, sigma=0.02)
            raw = pm.Normal("raw_" + group, 0, 1, dims=group)
            effect = pm.Deterministic("effect_" + group, (raw - pm.math.mean(raw)) * scale, dims=group)
            predictor = predictor + effect[encodings[group]]
        pm.Normal("observed", predictor, sigma=frame.se.to_numpy(), observed=frame["mean"].to_numpy())
        trace = pm.sample(draws=draws, tune=draws, chains=4, cores=1, random_seed=seed,
                          target_accept=0.95, progressbar=False, return_inferencedata=True)
        prior = pm.sample_prior_predictive(samples=1000, random_seed=seed)
    diagnostic = az.summary(trace, var_names=["mu", *["sigma_" + key for key in groups]])
    divergence = int(trace.sample_stats.diverging.sum())
    max_rhat = float(diagnostic.r_hat.max())
    min_ess = float(diagnostic.ess_bulk.min())
    valid = divergence == 0 and max_rhat < 1.01 and min_ess >= 400
    terms = []
    for group in groups:
        posterior = trace.posterior["effect_" + group].values.reshape(-1, len(categories[group]))
        prior_samples = prior.prior["effect_" + group].values.reshape(-1, len(categories[group]))
        for index, name in enumerate(categories[group]):
            samples = posterior[:, index]
            overlap = prior_overlap(samples, prior_samples[:, index])
            lower, upper = np.quantile(samples, [0.025, 0.975])
            terms.append({"group": group, "name": name, "mean": float(samples.mean()),
                          "lower": float(lower), "upper": float(upper), "overlap": overlap,
                          "interpretable": valid and overlap <= 0.9})
    # 共享股票日期的效应仍相关，独立测量误差似然仅作研究性记忆，不作为确认检验。
    return {"state": "RESEARCH_ONLY" if valid else "UNIDENTIFIABLE", "stage": stage,
            "terms": terms, "rhat": max_rhat, "ess": min_ess, "divergences": divergence,
            "rank": rank, "columns": len(columns),
            "dependence_warning": "结构共享股票日期，当前似然未建模完整跨结构测量协方差；不得用于正式判定"}


def next_probe(map_cells: list[dict[str, Any]], posterior: dict[str, Any], visited: set[str]) -> dict[str, Any] | None:
    """选择下一研究坐标；输入地图/后验/历史，返回一个格子，欠识别时优先析因补格。"""
    for coordinate in ("M2-F3", "M2-F1", "M1-F3", "M1-F1"):
        if coordinate not in visited:
            return next(cell for cell in map_cells if cell["id"] == coordinate)
    available = [cell for cell in map_cells if cell["status"] == "unexplored" and cell["id"] not in visited]
    if not available:
        return None
    terms = [term for term in posterior.get("terms", []) if term.get("interpretable")]
    if not terms:
        return available[0]
    uncertainty = {term["name"]: term["upper"] - term["lower"] for term in terms if term["group"] == "family"}
    return max(available, key=lambda cell: uncertainty.get(cell["family"], 0.04))


def reconcile_law_posterior(laws: list[dict[str, Any]], posterior: dict[str, Any]) -> list[dict[str, Any]]:
    """检查账本文字与后验项覆盖；返回缺口，模型不可解读时不自动生成市场规律。"""
    gaps = []
    terms = posterior.get("terms", [])
    for term in terms:
        if term.get("interpretable") and term["lower"] * term["upper"] > 0:
            if not any(term["name"] in law.get("model_terms", []) for law in laws):
                gaps.append({"kind": "missing_law", "term": term["name"]})
    names = {term["name"] for term in terms}
    for law in laws:
        missing = set(law.get("model_terms", [])) - names
        if missing:
            gaps.append({"kind": "unmodeled_law", "law": law["id"], "terms": sorted(missing)})
    return gaps
