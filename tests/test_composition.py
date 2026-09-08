"""组合回归管线：验证缺失与空仓语义、共识票数、重复信号、时序对齐和合并成本。"""

import numpy as np
import pandas as pd
import pytest

from composition.core import CompositionConfig, compile_gate, compose, holding_path, signed_rank
from composition.evaluation import evaluate_targets, transfer_comparison


def inputs() -> tuple[dict, dict]:
    """构造两个部分覆盖的正反信号；无参数，返回可手算的信号和冻结档案。"""
    dates = pd.bdate_range("2020-01-01", periods=4)
    a = pd.DataFrame([[-2., -1., 1., 2.]]*4, index=dates, columns=list("ABCD"))
    b = pd.DataFrame([[-2., 1., -1., 2.]]*4, index=dates, columns=list("ABCD"))
    signals = {"S-a": a, "S-b": b}
    specs = {sid: {"id":sid, "family":"M1" if sid == "S-a" else "M2", "operational":[sid],
                   "primary_horizon":1, "coverage":"in_pool"} for sid in signals}
    return signals, specs


def test_conflicts_close_positions_and_contributions_reconcile() -> None:
    """相反方向在 conflict_cash 下空仓；所有成分归因之和等于实际组合暴露。"""
    signals, specs = inputs()
    result = compose(signals, specs, CompositionConfig(mode="conflict_cash"))
    assert result["target"][["B", "C"]].eq(0).all().all()
    assert result["target"]["D"].gt(0).all()
    assert result["daily"].conflict_stocks.eq(2).all()
    allocated = result["contributions"].groupby("date").allocated_weight.sum()
    np.testing.assert_allclose(allocated, result["target"].sum(axis=1))
    assert result["target"].max().max() <= .05


def test_missing_source_is_not_a_zero_vote_and_union_preserves_symbols() -> None:
    """部分证券仅由一个结构覆盖；并联可以参与，共识必须等两个真实同向信号。"""
    signals, specs = inputs()
    signals["S-b"] = signals["S-b"].drop(columns="D")
    parallel = compose(signals, specs, CompositionConfig(mode="parallel"))
    consensus = compose(signals, specs, CompositionConfig(mode="consensus"))
    assert "D" in parallel["target"].columns
    assert parallel["target"].D.gt(0).all()
    assert consensus["target"].D.eq(0).all()
    signals["S-a"].loc[:, "D"] = np.nan
    missing = compose(signals, specs, CompositionConfig())
    assert missing["signed_path"].D.isna().all() and missing["target"].D.eq(0).all()


def test_exact_definition_does_not_double_count_or_vote() -> None:
    """复制同定义结构不能增加权重或共识票数，两个独立构造仍保持原输出。"""
    signals, specs = inputs()
    reference = compose(signals, specs, CompositionConfig(mode="consensus"))
    signals["S-copy"] = signals["S-a"].copy()
    specs["S-copy"] = {**specs["S-a"], "id":"S-copy"}
    duplicated = compose(signals, specs, CompositionConfig(mode="consensus"))
    pd.testing.assert_frame_equal(reference["target"], duplicated["target"])
    assert duplicated["aliases"] == {"S-copy":"S-a"}
    signals["S-copy"].iloc[0, 0] += 1
    with pytest.raises(ValueError, match="相同冻结定义"):
        compose(signals, specs, CompositionConfig())


def test_gates_use_frozen_cut_and_close_old_cohorts_without_future_leakage() -> None:
    """冻结阈值的 gate 对未知关闭，今日失效清除旧 cohort，未来修改不影响过去。"""
    signals, _ = inputs()
    frame = signals["S-a"]
    values = frame.copy()
    values.iloc[1] = np.nan
    values.iloc[2] = -10
    rule = {"field":"state", "cut_id":"fixed"}
    cuts = {"fixed":{"field":"state", "side":"high", "value":0.}}
    mask = compile_gate(rule, {"state":values}, cuts, frame)
    path = holding_path(frame, 3, mask)
    assert path.iloc[1:3].isna().all().all()
    changed = frame.copy(); changed.iloc[-1] = 999
    pd.testing.assert_frame_equal(path.iloc[:-1], holding_path(changed, 3, mask).iloc[:-1])
    with pytest.raises(ValueError, match="gate 只能"):
        compile_gate({**rule, "threshold":.5}, {"state":values}, cuts, frame)
    with pytest.raises(ValueError, match="字段或方向"):
        compile_gate({"field":"other", "cut_id":"fixed"}, {"state":values}, cuts, frame)


def test_ties_are_neutral_and_dates_cannot_be_silently_dropped() -> None:
    """并列信号不制造多头偏向；缺少日期必须报错而不是取交集。"""
    signals, specs = inputs()
    flat = signals["S-a"]*0
    assert signed_rank(flat).eq(0).all().all()
    signals["S-b"] = signals["S-b"].iloc[1:]
    with pytest.raises(ValueError, match="日期必须完全一致"):
        compose(signals, specs, CompositionConfig())


def test_transfer_cost_is_recomputed_after_netting_and_terminal_close() -> None:
    """轮流持有的两个账户合并成恒定持仓后，只剩入场及期末清仓转移。"""
    dates = pd.bdate_range("2020-01-01", periods=4)
    a = pd.DataFrame({"X":[.5,0,.5,0]}, index=dates)
    b = pd.DataFrame({"X":[0,.5,0,.5]}, index=dates)
    combined = (a+b)/2
    result = transfer_comparison({"a":a, "b":b}, combined, CompositionConfig())
    assert result["combined_transfer"] == .5
    assert result["combined_cost"] < result["component_equal_capital_cost"]
    daily, metrics = evaluate_targets(combined, combined*0, CompositionConfig())
    assert daily.iloc[0].buy_weight == .25 and daily.iloc[-1].sell_weight == .25
    assert metrics["research_total_return"] < 0


def test_missing_held_return_invalidates_whole_nav_without_dropping_dates() -> None:
    """持仓标签缺失不能填零或忽略；日期保留，完整业绩明确无效。"""
    dates = pd.bdate_range("2020-01-01", periods=4)
    target = pd.DataFrame({"X":[.2]*4}, index=dates)
    returns = pd.DataFrame({"X":[.01,np.nan,.01,.01]}, index=dates)
    daily, report = evaluate_targets(target, returns, CompositionConfig())
    assert len(daily) == 4 and daily.research_nav.isna().all()
    assert report["research_total_return"] is None
    assert report["state"] == "INVALID_RETURN_COVERAGE"
def test_active_universe_does_not_query_zero_weight_future_ipo() -> None:
    """零权重且未持有证券不查询合约，已有仓位即使目标为零也须参与卖出。"""
    from types import SimpleNamespace
    from backtest.execute_research_target import active_symbols

    class Positions(dict):
        """只接受实际已有键；缺失访问代表适配器错误查询了未上市证券。"""
        def __missing__(self, key: str) -> None:
            """拒绝访问未知证券；输入键，无正常返回。"""
            raise AssertionError("Future IPO queried")

    chosen = pd.Series({"future_ipo":0., "new_buy":.1, "held_sell":0.})
    positions = Positions({"held_sell":SimpleNamespace(quantity=100)})
    assert active_symbols(chosen, positions) == ["held_sell", "new_buy"]

def test_terminal_execution_uses_two_real_a_dates_and_preserves_signals() -> None:
    """最后信号须有次日成交和再下一日清仓；不能跨入 B 段或覆写原信号。"""
    from composition.replay import extend_execution_calendar

    calendar = pd.to_datetime(["2022-06-24", "2022-06-27", "2022-06-28", "2022-06-29", "2022-06-30"])
    target = pd.DataFrame({"X": [.1, .2, .3]}, index=calendar[:3])
    extended = extend_execution_calendar(target, calendar)
    pd.testing.assert_frame_equal(extended.iloc[:3], target)
    assert extended.iloc[-2:].eq(0).all().all()
    assert extended.index[-1] == pd.Timestamp("2022-06-30")
    with pytest.raises(ValueError, match="不足"):
        extend_execution_calendar(target, calendar[:-1])
