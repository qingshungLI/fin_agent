"""登记管线：受控词表形成机制地图，结构经过断言、DSL 与量纲检查后冻结。

四个冷启动坐标遵循 2×2 析因。手工种子明确标记 manual，不伪装成大模型输出。
"""

from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from engine.config import SLOTS
from engine.dsl import DIMENSIONS, compile_expression, evaluate

FAMILIES = [
    ("M1", "注意力冲击", "retail", "attention_bandwidth", "overreaction", "attention_decay"),
    ("M2", "流动性提供", "liquidity_provider", "inventory_risk", "temporary_impact", "inventory_unwind"),
    ("M3", "处置效应与锚定", "retail", "disposition_effect", "underreaction", "gradual_realization"),
    ("M4", "信息缓慢扩散", "limited_attention_inst", "processing_capacity", "underreaction", "peer_diffusion"),
    ("M5", "交易约束", "all", "hard_constraint", "unfinished_adjustment", "next_session"),
    ("M6", "被动资金与再平衡", "index_fund", "mandate_constraint", "temporary_impact", "post_event_reversal"),
    ("M7", "参与者结构", "mixed", "order_splitting", "information_asymmetry", "information_incorporation"),
    ("M8", "风险补偿与估值", "long_horizon_inst", "risk_aversion", "risk_premium", "slow_convergence"),
    ("M9", "不确定性解决", "all", "uncertainty_aversion", "ambiguity_discount", "event_resolution"),
    ("M10", "隔夜信息聚合", "mixed", "overnight_closure", "overnight_repricing", "intraday_absorption"),
]
FORMS = ["水平", "变化", "时序相对", "截面相对", "背离", "条件化", "事件化"]
FORM_CODES = ["F1_level", "F2_change", "F3_ts_relative", "F4_xs_relative", "F5_divergence", "F6_conditional", "F7_event"]
INFEASIBLE = {"M4": [1], "M5": [1, 2, 3, 4, 5], "M6": [1, 3, 5],
              "M7": [7], "M8": [2, 5, 7], "M9": [1, 2, 3, 4, 5]}
SEEDS = [("M2", 3), ("M2", 1), ("M1", 3), ("M1", 1)]


class Assertion(BaseModel):
    """登记可检验断言；参数含方向/阈值/周期，返回验证模型，必须在收益前固定。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^P[1-9][0-9]*$")
    kind: Literal["shape", "peak", "sign", "side"]
    subject: str
    relation: Literal["monotone_up", "monotone_down", "positive", "negative", "inside", "difference"]
    direction: Literal[-1, 1] = 1
    tolerance: float = Field(default=0, ge=0, lt=1)
    horizons: list[int] = Field(default_factory=lambda: [5])
    peak_range: list[int] = Field(default_factory=lambda: [1, 5])
    scope: str = "in_pool"
    attribution: str = Field(min_length=8)
    weight: float = Field(default=0.2, gt=0, le=1)
    prior_p: float = Field(default=0.6, ge=0.2, le=0.8)

    @model_validator(mode="after")
    def validate_assertion(self):
        relations = {"shape": {"monotone_up", "monotone_down"}, "peak": {"inside"},
                     "sign": {"positive", "negative"}, "side": {"difference"}}
        if self.relation not in relations[self.kind]:
            raise ValueError("Assertion kind and relation disagree")
        if len(self.horizons) != 1 or self.horizons[0] not in (1,3,5,10):
            raise ValueError("Each assertion freezes exactly one registered horizon")
        if len(self.peak_range) != 2 or not 1 <= self.peak_range[0] <= self.peak_range[1] <= 10:
            raise ValueError("Invalid frozen peak interval")
        if self.kind == "sign" and self.direction != (1 if self.relation == "positive" else -1):
            raise ValueError("Sign relation and direction disagree")
        return self


class Structure(BaseModel):
    """登记机制及三个算子化；输入标签和断言，要求旁证可观察且表达式不重复。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^S-[a-zA-Z0-9-]+$")
    name: str = Field(min_length=2, max_length=100)
    family: str
    form: int = Field(ge=1, le=7)
    mechanism: str = Field(min_length=10, max_length=3000)
    labels: dict[str, str]
    operational: list[str] = Field(min_length=3, max_length=3)
    assertions: list[Assertion] = Field(min_length=5, max_length=12)
    coverage: str = "in_pool"
    lineage: dict[str, Any] = Field(default_factory=lambda: {"parent": None, "operator": "seed", "origin": "manual"})
    primary_horizon: Literal[1, 3, 5, 10] = 5

    @model_validator(mode="after")
    def validate_structure(self) -> "Structure":
        """检查词表与断言完备性；返回自身，禁止将信号自身充当两个独立旁证。"""
        if set(self.labels) != set(SLOTS) or self.family not in {row[0] for row in FAMILIES}:
            raise ValueError("标签槽位或机制族不合法")
        for slot, value in self.labels.items():
            if value not in vocabulary_registry(slot):
                raise ValueError(f"未登记词表: {slot}={value}")
        if self.form in INFEASIBLE.get(self.family, []):
            raise ValueError("该机制/表现形式已被登记为不可行")
        if self.labels["form"] != FORM_CODES[self.form - 1]:
            raise ValueError("Representation label disagrees with map coordinate")
        if len(set(self.operational)) != 3:
            raise ValueError("三个表达式必须不同")
        if len({a.id for a in self.assertions}) != len(self.assertions):
            raise ValueError("断言 ID 重复")
        if abs(sum(a.weight for a in self.assertions) - 1) > 1e-8:
            raise ValueError("断言权重必须在冻结时合计为 1")
        if not any(a.kind == "shape" for a in self.assertions):
            raise ValueError("至少需要一条形状断言")
        sides = [a for a in self.assertions if a.kind == "side"]
        if len({a.subject for a in sides}) < 2:
            raise ValueError("至少需要两个不同可观察量的旁证")
        if any(not set(a.horizons) <= {1, 3, 5, 10} for a in self.assertions):
            raise ValueError("首版断言周期仅支持 1/3/5/10")
        return self


def vocabulary_registry(slot: str) -> list[str]:
    """返回槽位受控取值；输入槽位名，返回排序词表，未知槽位拒绝。"""
    if slot not in SLOTS:
        raise ValueError("未知词表槽位")
    return FORM_CODES if slot == "form" else sorted({row[SLOTS.index(slot) + 2] for row in FAMILIES})


def build_map() -> list[dict[str, Any]]:
    """生成 70 格机制地图；无参数，返回带不可行原因及周期暂缓状态的格子。"""
    result = []
    for row in FAMILIES:
        for form in range(1, 8):
            blocked = form in INFEASIBLE.get(row[0], [])
            result.append({"id": f"{row[0]}-F{form}", "family": row[0], "family_name": row[1],
                           "form": form, "form_name": FORMS[form - 1],
                           "status": "infeasible" if blocked else "deferred_horizon" if row[0] == "M8" else "unexplored",
                           "reason": "状态/事件不能直接作为连续信号，或构造共线" if blocked else
                           "机制周期超过首版 10 日范围" if row[0] == "M8" else "尚未登记研究"})
    return result


def seed_structure(index: int, run_id: str) -> Structure:
    """构造 2×2 手工事前种子；输入序号和运行 ID，返回正向交易信号定义。"""
    family, form = SEEDS[index % len(SEEDS)]
    row = next(row for row in FAMILIES if row[0] == family)
    if family == "M2":
        expressions = ["neg(ts_z(ret_5d, 60))", "neg(xs_rank(ret_5d))", "neg(sub(ret_5d, industry_mean(ret_5d)))"]
        mechanism = "短期订单失衡造成临时价格偏离；承接者承担存货风险，价格在存货出清后回归。该补偿在流动性较差和竞价价差较宽的股票中应更强。"
        sides = [("amihud_pct", 1), ("auction_spread_pct", 1)]
    else:
        expressions = ["neg(ts_z(log(turnover_today), 60))", "neg(xs_rank(turnover_today))", "neg(sub(log(turnover_today), industry_mean(log(turnover_today))))"]
        mechanism = "异常换手吸引有限注意力并形成短期价格压力；关注消退后价格回归。注意力机制预测小市值、低平均单笔成交额的股票中反转更强。"
        sides = [("market_cap_pct", -1), ("avg_trade_size_pct", -1)]
    if form == 1:
        if family == "M2":
            expressions = ["neg(xs_z(ret_5d))", "neg(xs_rank(ret_3d))",
                           "neg(sub(ret_1d, industry_mean(ret_1d)))"]
        else:
            expressions = ["neg(xs_rank(turnover_today))",
                           "neg(xs_z(log(turnover_today)))",
                           "neg(xs_rank(avg_trade_size))"]
    assertions = [
        Assertion(id="P1", kind="shape", subject="dose_shape", relation="monotone_up",
                  attribution="交易信号已取反，信号升高对应更强的未来反转补偿"),
        Assertion(id="P2", kind="peak", subject="peak_horizon", relation="inside",
                  peak_range=[1, 5] if family == "M2" else [3, 10],
                  attribution="存货或注意力的消退应在短周期完成，峰值不是自由调参"),
        Assertion(id="P3", kind="sign", subject="effect_sign", relation="positive",
                  attribution="三个表达式均已转换为预测收益的正向交易信号"),
    ]
    assertions += [Assertion(id=f"P{i + 4}", kind="side", subject=name, relation="difference",
                             direction=direction, attribution=mechanism) for i, (name, direction) in enumerate(sides)]
    return Structure(id=f"S-{run_id}-{index + 1:03d}", name=f"{row[1]} · {FORMS[form - 1]}",
                     family=family, form=form, mechanism=mechanism,
                     labels=dict(zip(SLOTS, [*row[2:], FORM_CODES[form - 1]])),
                     operational=expressions, assertions=assertions)


def register_cell(
    expression: str, fields: dict[str, pd.DataFrame], cuts: dict[str, dict[str, Any]],
    confounders: list[str] | None = None,
) -> dict[str, Any]:
    """执行尺度、边界、截断不变性与混淆检查；返回注册报告，未通过时拒绝。"""
    compiled = compile_expression(expression, set(fields), cuts)
    # Only referenced inputs plus implicit rank/industry context need scale copies.
    selected = set(compiled.dependencies) | set(confounders or []) | ({"in_pool", "industry"} & set(fields))
    fields = {k: v for k, v in fields.items() if k in selected}
    value = evaluate(expression, fields, cuts)
    if not value.notna().any().any():
        raise ValueError(f"表达式没有有效观测: {expression}")
    cutoff = max(2, len(value) * 3 // 4)
    truncated = evaluate(expression, {k: v.iloc[:cutoff] for k, v in fields.items()}, cuts)
    if not np.allclose(value.iloc[:cutoff], truncated, equal_nan=True):
        raise ValueError("特征在历史截断后变化，存在前视")
    scaled = {k: v * 10 ** DIMENSIONS[k] if DIMENSIONS.get(k, 0) else v
              for k, v in fields.items()}
    scale_value = evaluate(expression, scaled, cuts)
    target = value * 10 ** compiled.scale_exponent
    # log 的加性尺度变化在后续标准化后应消除；非标准化 log 不登记为信号。
    if not np.allclose(scale_value, target, equal_nan=True, rtol=1e-5, atol=1e-8):
        raise ValueError(f"表达式不满足声明的价格尺度变换: {expression}")
    for name in confounders or []:
        correlation = value.stack().corr(fields[name].stack())
        if pd.notna(correlation) and abs(correlation) >= 0.3:
            raise ValueError(f"未剥离混淆变量 {name}: |rho|>=0.3")
    return {"expression": expression, "scale_exponent": compiled.scale_exponent,
            "dependencies": compiled.dependencies, "missing": int(value.isna().sum().sum()),
            "lookahead": "pass", "scale": "pass"}


def freeze_cuts(fields: dict[str, pd.DataFrame], names: list[str], seed: int) -> dict[str, dict[str, Any]]:
    """在 A 训练块冻结百分位切点；返回带置信区间的表，重叠区间合并不增加自由度。"""
    rng = np.random.default_rng(seed)
    result = {}
    for name in names:
        values = fields[name].to_numpy(dtype=float)
        finite = values[np.isfinite(values)]
        if len(finite) < 100:
            continue
        quantiles = np.linspace(0.1, 0.9, 5)
        point = np.quantile(finite, quantiles)
        samples = []
        for _ in range(200):
            starts = rng.integers(0, max(1, len(values) - 9), size=max(1, len(values) // 10))
            indices = np.minimum(starts[:, None] + np.arange(10), len(values) - 1).ravel()
            samples.append(np.nanquantile(values[indices], quantiles))
        lower, upper = np.quantile(samples, [0.025, 0.975], axis=0)
        previous_upper = -np.inf
        for j, threshold in enumerate(point):
            if lower[j] <= previous_upper or (j and threshold == point[j - 1]):
                continue
            for side in ("low", "high"):
                result[f"{name}_q{j}_{side}"] = {"field": name, "value": float(threshold), "side": side,
                                                "lower": float(lower[j]), "upper": float(upper[j])}
            previous_upper = upper[j]
    return result


def check_convergent_orientation(structure, fields, cuts):
    """Reject strongly contradictory operationalizations without reading labels."""
    from engine.metrics import daily_ic
    values = [evaluate(expr, fields, cuts) for expr in structure.operational]
    correlations = []
    for i in range(3):
        for j in range(i + 1, 3):
            correlation = daily_ic(values[i], values[j]).mean()
            if np.isfinite(correlation) and correlation < -0.2:
                raise ValueError("Operationalizations have contradictory orientations; no returns were read")
            correlations.append(float(correlation) if np.isfinite(correlation) else None)
    return {"pairwise_feature_correlations": correlations, "uses_returns": False}
