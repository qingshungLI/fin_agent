"""组合管线：验证信号与冻结 gate，按原周期展开路径，去重后路由，投影为现金约束持仓。

组合不改动源结构的方向与标签。不读取未来收益来选结构、调 gate 或估权重。
新增共识 gate 是独立的 A 段研究假设；本模块永远不自行授予正式资格。
"""

from dataclasses import asdict, dataclass
from itertools import combinations
from typing import Any, Literal

import numpy as np
import pandas as pd

from engine.audit import digest


@dataclass(frozen=True)
class CompositionConfig:
    """冻结组合规则；输入模式、参与票数及风险约束，假设所有成分方向已冻结。"""

    mode: Literal["parallel", "conflict_cash", "consensus"] = "conflict_cash"
    min_agree: int = 2
    max_positions: int = 50
    max_weight: float = .05
    min_cash: float = .05
    commission_bp: float = 3.
    slippage_bp: float = 5.
    stamp_tax_bp: float = 10.

    def __post_init__(self) -> None:
        """验证参数边界；无输入返回，不接受隐式收益优化或非法风险约束。"""
        if self.mode not in {"parallel", "conflict_cash", "consensus"}:
            raise ValueError("未知组合门控模式")
        if type(self.min_agree) is not int or self.min_agree < 2:
            raise ValueError("共识 gate 至少需要两个独立构造成分")
        if type(self.max_positions) is not int or self.max_positions < 1:
            raise ValueError("持仓数量必须为正整数")
        values = [self.max_weight, self.min_cash, self.commission_bp, self.slippage_bp, self.stamp_tax_bp]
        if not np.isfinite(values).all() or not 0 < self.max_weight <= 1 or not 0 <= self.min_cash < 1:
            raise ValueError("风险与成本参数无效")
        if min(values[2:]) < 0:
            raise ValueError("成本不能为负")


def validate_frame(frame: pd.DataFrame, name: str) -> None:
    """校验日期和证券矩阵；参数为信号及名称，无返回，NaN 合法而无穷值非法。"""
    if frame.empty or not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError(f"{name}: 需要非空交易日矩阵")
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates or frame.columns.has_duplicates:
        raise ValueError(f"{name}: 日期必须有序且日期/证券唯一")
    if not all(isinstance(symbol, str) for symbol in frame.columns):
        raise ValueError(f"{name}: 证券代码必须为字符串")
    if np.isinf(frame.to_numpy(dtype=float)).any():
        raise ValueError(f"{name}: 不允许无穷值")


def compile_gate(rule: dict[str, Any], fields: dict[str, pd.DataFrame],
                 cuts: dict[str, dict[str, Any]], prototype: pd.DataFrame) -> pd.DataFrame:
    """把冻结切点规则编译为掩码。

    Args:
        rule: 仅含 field、cut_id；不接受临时数值阈值或任意公式。
        fields: 当日可用状态矩阵。
        cuts: 已冻结的字段、方向和阈值表。
        prototype: 输出索引原型，不允许偷偷改交易日。
    Returns:
        pd.DataFrame: 布尔门控，未知值关闭；新 gate 仍需独立检验。
    """
    if set(rule) != {"field", "cut_id"} or rule["cut_id"] not in cuts:
        raise ValueError("gate 只能引用冻结的 field/cut_id")
    cut = cuts[rule["cut_id"]]
    if cut["field"] != rule["field"] or cut["side"] not in {"high", "low"}:
        raise ValueError("gate 字段或方向与冻结切点不符")
    if not np.isfinite(cut["value"]) or rule["field"] not in fields:
        raise ValueError("gate 输入字段或阈值无效")
    values = fields[rule["field"]]
    validate_frame(values, rule["field"])
    if not values.index.equals(prototype.index) or not prototype.columns.isin(values.columns).all():
        raise ValueError("gate 字段索引未对齐")
    values = values.reindex(columns=prototype.columns)
    condition = values.ge(cut["value"]) if cut["side"] == "high" else values.le(cut["value"])
    return condition & values.notna()


def signed_rank(signal: pd.DataFrame) -> pd.DataFrame:
    """将截面信号映射到对称秩；输入已定向信号，返回 [-1,1]，全并列为零、缺失为 NaN。"""
    rank = signal.rank(axis=1, method="average")
    count = signal.count(axis=1)
    centered = rank.sub((count + 1) / 2, axis=0).div(((count - 1) / 2).where(count > 1), axis=0)
    return centered.where(count > 1, 0., axis=0).where(signal.notna())


def holding_path(signal: pd.DataFrame, horizon: int, gate: pd.DataFrame) -> pd.DataFrame:
    """展开冻结周期的线性衰减路径；输入定向信号/周期/当日 gate，返回覆盖外 NaN 的路径。"""
    if horizon not in (1, 3, 5, 10):
        raise ValueError("周期必须来自冻结的 1/3/5/10 日表")
    if not gate.index.equals(signal.index) or not gate.columns.equals(signal.columns):
        raise ValueError("gate 与信号未对齐")
    weights = signed_rank(signal.where(gate))
    output = pd.DataFrame(0., index=signal.index, columns=signal.columns)
    for lag in range(horizon):
        output += weights.shift(lag).fillna(0) * (1 - lag / horizon)
    # 原覆盖区域今日失效时撤销旧信号，不能让历史 cohort 穿越 gate。
    output = output.where(gate & signal.notna())
    gross = output.abs().sum(axis=1)
    return output.div(gross.where(gross > 0, 1.), axis=0)


def long_projection(score: pd.DataFrame, config: CompositionConfig) -> pd.DataFrame:
    """投影为多头目标持仓；输入有方向路径和冻结约束，返回非负权重，空白区域保持现金。"""
    output = pd.DataFrame(0., index=score.index, columns=score.columns)
    for date, row in score.iterrows():
        positive = row[row > 0].sort_index().sort_values(ascending=False, kind="stable")
        chosen = positive.iloc[:config.max_positions]
        if chosen.empty:
            continue
        # 保留组合实际多头预算；空仓/冲突不会被重新放大到满仓。
        budget = min(1 - config.min_cash, float(positive.sum()) * (1 - config.min_cash))
        weights = chosen / chosen.sum() * budget
        output.loc[date, chosen.index] = weights.clip(upper=config.max_weight)
    return output


def relation_matrix(paths: dict[str, pd.DataFrame], specs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """诊断覆盖、方向和标签关系；输入持仓路径与原规格，返回不参与调权的关系表。"""
    rows = []
    for left, right in combinations(paths, 2):
        a, b = paths[left], paths[right]
        common, union = a.notna() & b.notna(), a.notna() | b.notna()
        x, y = a.to_numpy(), b.to_numpy()
        valid = common.to_numpy()
        xv, yv = x[valid], y[valid]
        varying = len(xv) > 1 and np.std(xv) > 0 and np.std(yv) > 0
        correlation = float(np.corrcoef(xv, yv)[0, 1]) if varying else None
        conflicts = int(((a > 0) & (b < 0) | (a < 0) & (b > 0)).sum().sum())
        same_family = specs[left]["family"] == specs[right]["family"]
        overlap = int(common.sum().sum())
        rows.append({"source": left, "target": right, "overlap": overlap,
                     "union": int(union.sum().sum()), "conflicts": conflicts, "correlation": correlation,
                     "same_family": same_family,
                     "interpretation": "disjoint" if not overlap else "conflicting" if conflicts else "aligned",
                     "action": "diagnostic_only; no full-A correlation-based weight fitting"})
    return rows


def compose(signals: dict[str, pd.DataFrame], specs: dict[str, dict[str, Any]],
            config: CompositionConfig, gates: dict[str, pd.DataFrame] | None = None) -> dict[str, Any]:
    """把多个结构组合成持仓与可审查 gate 状态。

    Args:
        signals: 源结构第一表达式，保持已冻结方向和原有覆盖。
        specs: 每个源结构的原冻结规格。
        config: 在读取组合业绩之前冻结的规则。
        gates: 可选新增状态门控，仅能关闭原覆盖；不能凭空启用缺失信号。
    Returns:
        dict: 多头目标、带符号路径、逐日路由、成分贡献和关系诊断；始终研究性输出。
    """
    if len(signals) < 2 or set(signals) != set(specs):
        raise ValueError("组合需要至少两个有对应冻结档案的结构")
    if gates and set(gates) - set(signals):
        raise ValueError("gate 引用了未知结构")
    dates = next(iter(signals.values())).index
    symbols = sorted(set().union(*(set(frame.columns) for frame in signals.values())))
    paths, aliases, keys, representatives = {}, {}, {}, {}
    source_records = []
    for sid in sorted(signals):
        frame = signals[sid]
        validate_frame(frame, sid)
        if not frame.index.equals(dates):
            raise ValueError("结构日期必须完全一致，不能按交集静默丢失历史")
        frame = frame.reindex(columns=symbols)
        gate = frame.notna()
        if gates and sid in gates:
            supplied = gates[sid]
            if not supplied.index.equals(dates) or not supplied.columns.equals(frame.columns):
                raise ValueError("外部 gate 必须按证券并集明确对齐")
            if not supplied.isin([True, False]).all().all():
                raise ValueError("外部 gate 必须是无缺失布尔掩码")
            gate &= supplied
        spec = specs[sid]
        if spec.get("id") != sid:
            raise ValueError("源结构 ID 与档案不符")
        identity = digest({"signal": spec["operational"][0], "coverage": spec["coverage"],
                           "horizon": spec["primary_horizon"]})
        if identity in keys:
            parent = keys[identity]
            if not frame.equals(signals[parent].reindex(columns=symbols)) or not gate.equals(representatives[parent]):
                raise ValueError("相同冻结定义产生不同数据或 gate，不可当作重复成分")
            aliases[sid] = parent
            continue
        keys[identity] = sid
        representatives[sid] = gate
        path = holding_path(frame, spec["primary_horizon"], gate)
        paths[sid] = path
        source_records.append(pd.DataFrame({"date": dates, "structure": sid,
            "eligible_stocks": gate.sum(axis=1), "positive_stocks": (path > 0).sum(axis=1),
            "negative_stocks": (path < 0).sum(axis=1)}))
    if len(paths) < 2:
        raise ValueError("去重后不足两个独立构造成分")
    if config.mode == "consensus" and config.min_agree > len(paths):
        raise ValueError("共识票数超过独立构造成分数")
    prototype = next(iter(paths.values()))
    positive = pd.DataFrame(0, index=dates, columns=symbols, dtype="int16")
    negative, covered = positive.copy(), positive.copy()
    score = prototype.fillna(0) * 0
    for path in paths.values():
        positive += path.gt(0).astype("int16")
        negative += path.lt(0).astype("int16")
        covered += path.notna().astype("int16")
        score += path.fillna(0) / len(paths)
    conflict = (positive > 0) & (negative > 0)
    active = covered > 0
    if config.mode == "conflict_cash":
        active &= ~conflict
    elif config.mode == "consensus":
        active &= ((positive >= config.min_agree) & (negative == 0)) | ((negative >= config.min_agree) & (positive == 0))
    routed = score.where(active, 0).where(covered > 0)
    target = long_projection(routed, config)
    contribution = []
    denominator = sum(p.clip(lower=0).fillna(0) for p in paths.values())
    for sid, path in paths.items():
        # 贡献按实际生效的成分绝对强度分摊；总和严格等于最终目标持仓。
        share = path.clip(lower=0).fillna(0)
        allocated = target * share.div(denominator.where(denominator > 0)).fillna(0)
        contribution.append(pd.DataFrame({"date": dates, "structure": sid,
            "allocated_weight": allocated.sum(axis=1), "routed_signed_gross": (path.where(active).abs().sum(axis=1) / len(paths))}))
    daily = pd.DataFrame({"covered_stocks": (covered > 0).sum(axis=1), "active_stocks": active.sum(axis=1),
        "conflict_stocks": conflict.sum(axis=1), "gate_closed_stocks": ((covered > 0) & ~active).sum(axis=1),
        "held_stocks": (target > 0).sum(axis=1), "long_exposure": target.sum(axis=1),
        "cash_target": 1 - target.sum(axis=1)}, index=dates)
    return {"target": target, "signed_path": routed, "daily": daily,
            "contributions": pd.concat(contribution, ignore_index=True),
            "source_routes": pd.concat(source_records, ignore_index=True),
            "relations": relation_matrix(paths, specs), "aliases": aliases,
            "representatives": list(paths), "config": asdict(config), "formal": False}