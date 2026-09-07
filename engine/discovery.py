"""发现管线：A 段影响贡献先做均值/方差分流，块交叉拟合构造 R-learning 残差。

honest 浅树只在冻结切点上搜索，叶子估计使用独立日期块。输出给提案器的只有变量名和频率。
确认矩检验独立调用，同日股票共享块乘子；探索重复切分不得读取正式 B/H。
"""

from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.tree import DecisionTreeRegressor

from engine.config import ResearchConfig
from engine.data import MarketPanel
from engine.metrics import summarize, holm


def purged_folds(dates: np.ndarray, folds: int = 5, purge: int = 15) -> list[tuple[np.ndarray, np.ndarray]]:
    """按完整日期构造 K 折及隔离带；输入逐行日期，返回训练/验证行掩码。"""
    unique = np.unique(dates)
    if len(unique) < folds * (2 * purge + 5):
        raise ValueError("交易日不足以构造带 purge 的交叉拟合")
    positions = np.searchsorted(unique, dates)
    output = []
    for indices in np.array_split(np.arange(len(unique)), folds):
        test = (positions >= indices[0]) & (positions <= indices[-1])
        train = (positions < indices[0] - purge) | (positions > indices[-1] + purge)
        if not train.any() or not test.any():
            raise ValueError("purge 后产生空训练或验证集")
        output.append((train, test))
    return output


def orthogonalize(frame: pd.DataFrame, controls: list[str]) -> pd.DataFrame:
    """在单一授权段独立交叉拟合收益和信号；返回残差长表，行业哑变量无序处理。"""
    required = ["date", "symbol", "f", "r", *controls]
    if frame[required].isna().any().any():
        raise ValueError("交叉拟合输入存在缺失；必须先记录并剔除完整案例外观测")
    design = pd.get_dummies(frame[controls], columns=[c for c in controls if frame[c].dtype == object], dtype=float)
    if design.shape[1] == 0 or not np.isfinite(design.to_numpy()).all():
        raise ValueError("控制变量为空或包含非有限值")
    result = frame.copy()
    result["r_resid"], result["f_resid"] = np.nan, np.nan
    for train, test in purged_folds(frame.date.to_numpy()):
        for target in ("r", "f"):
            model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
            model.fit(design.loc[train], frame.loc[train, target])
            result.loc[test, target + "_resid"] = frame.loc[test, target] - model.predict(design.loc[test])
    return result


def make_sample(panel: MarketPanel, signal: pd.DataFrame, horizon: int, moderators: list[str]) -> pd.DataFrame:
    """构造完整案例的交叉拟合输入；返回长表，所有控制变量只用当日信息。"""
    fields = panel.fields
    matrices = {"f": signal, "r": panel.labels[f"industry_resid_{horizon}"],
                "log_cap": np.log(fields["market_cap"].where(fields["market_cap"] > 0)),
                "volatility": fields["realized_vol"],
                "log_turnover": np.log(fields["turnover_today"].where(fields["turnover_today"] > 0)),
                "industry": fields["industry"], **{name: fields[name] for name in moderators}}
    stacked = pd.concat({key: value.stack() for key, value in matrices.items()}, axis=1)
    stacked.index.names = ["date", "symbol"]
    return stacked.replace([np.inf, -np.inf], np.nan).dropna().reset_index()


def variance_vs_mean_screen(
    contribution: pd.DataFrame, fields: dict[str, pd.DataFrame], candidates: list[str], config: ResearchConfig,
) -> dict[str, Any]:
    """对 Psi 的日期内中心化贡献做均值/方差分流；返回经候选校正的探索诊断。"""
    values = contribution.to_numpy(dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size < 100:
        return {"mean_shift": [], "variance_only": [], "rows": []}
    lower, upper = np.quantile(finite, [0.01, 0.99])
    winsor = contribution.clip(lower, upper)
    centered = winsor.sub(winsor.mean(axis=1), axis=0)
    rows = []
    for name in candidates:
        if name not in fields:
            continue
        z = fields[name]
        groups = np.ceil(z / 20).clip(1, 5)
        means = pd.DataFrame({i: centered.where(groups == i).mean(axis=1) for i in range(1, 6)})
        residual = centered.copy()
        for i in range(1, 6):
            residual = residual.mask(groups == i, centered.sub(means[i], axis=0))
        variances = pd.DataFrame({i: residual.pow(2).where(groups == i).mean(axis=1) for i in range(1, 6)})
        mean_tests = [summarize(means[i] - means[3], 5, config) for i in (1, 2, 4, 5)]
        var_tests = [summarize(variances[i] - variances[3], 5, config) for i in (1, 2, 4, 5)]
        mean_p = min(1.0, 4 * min(min(test["p"], test["p_negative"]) * 2 for test in mean_tests))
        var_p = min(1.0, 4 * min(min(test["p"], test["p_negative"]) * 2 for test in var_tests))
        rows.append({"name": name, "mean_p": mean_p, "variance_p": var_p})
    adjusted_mean = holm([row["mean_p"] for row in rows])
    adjusted_var = holm([row["variance_p"] for row in rows])
    for row, mean_p, var_p in zip(rows, adjusted_mean, adjusted_var):
        row.update(mean_adjusted=mean_p, variance_adjusted=var_p)
    return {"mean_shift": [row["name"] for row in rows if row["mean_adjusted"] < 0.05],
            "variance_only": [row["name"] for row in rows if row["variance_adjusted"] < 0.05 and row["mean_adjusted"] >= 0.05],
            "variance_scaling_candidates": [row["name"] for row in rows if row["variance_adjusted"] < 0.05],
            "rows": rows}


def blade_icm(frame: pd.DataFrame, moderator: str, cut: float, horizon: int, config: ResearchConfig) -> dict[str, Any]:
    """检验冻结门函数的正交交互矩；返回块乘子 p/e，同一时间块使用同一乘子。"""
    from engine.evidence import calibrate_p_to_e

    residuals = orthogonalize(frame, ["log_cap", "volatility", "log_turnover", "industry"])
    f, r = residuals.f_resid.to_numpy(), residuals.r_resid.to_numpy()
    h = np.where(residuals[moderator].to_numpy() > cut, 1.0, -1.0)
    denom = np.dot(f, f)
    if denom <= 1e-12:
        return {"state": "untested", "p": 1.0, "reason": "信号残差退化"}
    tau = float(np.dot(f, r) / denom)
    interaction = f * h
    # 剔除交互工具在主信号上的投影，使估计 tau0 的误差不进入一阶检验。
    instrument = interaction - f * np.dot(f, interaction) / denom
    score = (r - tau * f) * instrument
    daily = pd.Series(score).groupby(residuals.date.to_numpy()).mean()
    block_length = max(10, 2 * horizon)
    if len(daily) < 20 * block_length:
        return {"state": "untested", "p": 1.0, "reason": "正交矩少于 20 个独立日期块"}
    observed = float(daily.sum())
    centered = daily.to_numpy() - daily.mean()
    blocks = np.arange(len(daily)) // block_length
    block_sums = np.bincount(blocks, weights=centered)
    rng = np.random.default_rng(config.seed)
    null = rng.normal(size=(config.n_boot, len(block_sums))) @ block_sums
    p = float((1 + np.count_nonzero(np.abs(null) >= abs(observed))) / (config.n_boot + 1))
    return {"state": "measured", "p": p, "e_experimental": calibrate_p_to_e(p),
            "tau_main": tau, "score": float(daily.mean()), "blocks": len(block_sums)}


def forest_propose(
    frame: pd.DataFrame, candidates: list[str], cuts: dict[str, dict[str, Any]], config: ResearchConfig,
) -> dict[str, Any]:
    """训练 honest R-learning 浅森林；返回变量名频率和内部诊断，切点来自冻结表。"""
    if not candidates or len(candidates) > 5:
        return {"candidates": [], "reason": "候选应由机制约束在 1–5 个"}
    residual = orthogonalize(frame, ["log_cap", "volatility", "log_turnover", "industry"])
    dates = np.sort(residual.date.unique())
    cutoff = len(dates) // 2
    train = residual.date.isin(dates[:max(0, cutoff - 15)]).to_numpy()
    estimate = residual.date.isin(dates[cutoff:]).to_numpy()
    if cutoff < 400 or residual.loc[train, "symbol"].nunique() < 100:
        return {"candidates": [], "reason": "honest 半段不足 20 个日期块及 100 只证券"}
    features = []
    for name in candidates:
        thresholds = sorted({row["value"] for row in cuts.values() if row["field"] == name})
        if not thresholds:
            raise ValueError(f"森林候选没有冻结切点: {name}")
        features.append(np.digitize(residual[name], thresholds))
    design = np.column_stack(features)
    f, r = residual.f_resid.to_numpy(), residual.r_resid.to_numpy()
    eligible = np.abs(f) > 1e-6
    target = np.divide(r, f, out=np.zeros_like(r), where=eligible)
    weights = f ** 2
    rng = np.random.default_rng(config.seed)
    votes = np.zeros(len(candidates))
    valid_trees, leaf_effects = 0, []
    for tree_index in range(config.n_trees):
        training_dates = dates[:cutoff - 15]
        starts = rng.integers(0, len(training_dates) - 19, size=max(1, len(training_dates) // 20))
        sampled_days = training_dates[(starts[:, None] + np.arange(20)).ravel()]
        multiplicity = pd.Series(sampled_days).value_counts()
        bootstrap_weights = residual.date.map(multiplicity).fillna(0).to_numpy() * weights
        fitting = train & eligible & (bootstrap_weights > 0)
        model = DecisionTreeRegressor(max_depth=2, random_state=config.seed + tree_index, min_samples_leaf=100)
        model.fit(design[fitting], target[fitting], sample_weight=bootstrap_weights[fitting])
        leaves = model.apply(design)
        accepted = True
        effects = []
        for leaf in np.unique(leaves):
            for half in (train, estimate):
                selected = (leaves == leaf) & half & eligible
                independent_blocks = residual.loc[selected, "date"].map({date: i // 20 for i, date in enumerate(dates)}).nunique()
                if independent_blocks < 20 or residual.loc[selected, "symbol"].nunique() < 100:
                    accepted = False
            selected = (leaves == leaf) & estimate & eligible
            denominator = float(np.sum(weights[selected]))
            if denominator > 1e-12:
                effects.append(float(np.dot(f[selected], r[selected]) / denominator))
        if accepted:
            valid_trees += 1
            used = set(model.tree_.feature[model.tree_.feature >= 0])
            for variable in used:
                votes[variable] += 1
            leaf_effects.extend(effects)
    return {"candidates": [{"name": name, "frequency": float(vote / max(1, config.n_trees))}
                           for name, vote in zip(candidates, votes) if vote > 0],
            "valid_trees": valid_trees, "trees": config.n_trees,
            "internal_leaf_effects": leaf_effects, "reason": "候选不代表因果识别；不向提案岗位提供效应方向"}


def repeat_splits(
    panel: MarketPanel, signal: pd.DataFrame, candidates: list[str], cuts: dict[str, Any], config: ResearchConfig,
) -> dict[str, Any]:
    """仅在 A 段重复时间块训练/验证；返回 2×p 中位数与入选频率，不访问正式确认段。"""
    frame = make_sample(panel, signal, 5, candidates)
    dates = np.sort(frame.date.unique())
    votes = dict.fromkeys(candidates, 0)
    p_values = []
    for index in range(config.n_splits):
        fraction = 0.55 + 0.2 * index / max(1, config.n_splits - 1)
        boundary = int(len(dates) * fraction)
        train = frame[frame.date.isin(dates[:max(0, boundary - 15)])].reset_index(drop=True)
        validation = frame[frame.date.isin(dates[boundary:])].reset_index(drop=True)
        local = config.model_copy(update={"seed": config.seed + index})
        if train.date.nunique() < 400 or validation.date.nunique() < 200:
            p_values.append(1.0)
            continue
        proposed = forest_propose(train, candidates, cuts, local)
        if not proposed["candidates"]:
            p_values.append(1.0)
            continue
        strongest = max(proposed["candidates"], key=lambda item: item["frequency"])["name"]
        votes[strongest] += 1
        threshold = next(row["value"] for row in cuts.values() if row["field"] == strongest)
        p_values.append(blade_icm(validation, strongest, threshold, 5, local)["p"])
    return {"p_median": min(1.0, 2 * float(np.median(p_values))),
            "selection_frequency": {key: value / config.n_splits for key, value in votes.items()},
            "fold_p": p_values, "segment": "A_internal_only"}


def evolve_operators(structure: Any, results: list[dict[str, Any]], confirmed_conditions: list[str]) -> list[dict[str, Any]]:
    """根据断言矩阵提出演化动作；返回提案元数据，所有新组合仍需新 ID 和完整检验。"""
    output = []
    if any(row["kind"] in ("shape", "sign") and row["state"] != "hold" for row in results):
        output.append({"operator": "horizontal", "parent": structure.id, "family": structure.family,
                       "forms": [form for form in (1, 3, 5) if form != structure.form]})
    if any(row["kind"] == "side" and row["state"] == "violated" for row in results):
        output.append({"operator": "cross_family", "parent": structure.id, "origin": "data_informed_A"})
    for condition in confirmed_conditions:
        output.append({"operator": "crossover", "parent": structure.id, "condition": condition})
    return output


def should_stop(left: np.ndarray, right: np.ndarray, mde: float, min_effect: float) -> bool:
    """根据功效与持仓差异停止搜索；输入两路径和门槛，返回布尔，零换手单独处理。"""
    if mde > min_effect:
        return True
    if left.shape != right.shape:
        raise ValueError("持仓路径形状不同")
    valid = np.isfinite(left) & np.isfinite(right)
    if valid.sum() < 3:
        return True
    if np.allclose(left[valid], right[valid]):
        return True
    corr = np.corrcoef(left[valid], right[valid])[0, 1]
    turnover_left = np.nansum(np.abs(np.diff(left, axis=0)))
    turnover_right = np.nansum(np.abs(np.diff(right, axis=0)))
    return bool(corr > 0.9 and abs(turnover_left - turnover_right) <= 0.1 * max(turnover_left, 1e-12))
