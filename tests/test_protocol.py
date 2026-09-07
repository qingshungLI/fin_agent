"""协议验收：用小型合成面板验证防前视、统计边界、审计链和符号一致性。

测试不依赖真实 Parquet，避免把供应商数据状态和算法协议混为一谈；真实数据由 run_engine 单独做严格阻断验收。
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from engine.audit import AuditStore
from engine.catalog import build_map
from engine.consistency import balance_check
from engine.dsl import compile_expression, evaluate
from engine.evidence import merge_e, bet_on_assertion
from engine.metrics import daily_ic, holm


def panel() -> dict[str, pd.DataFrame]:
    """生成 40 日×20 股的有限历史矩阵；无未来列，供 DSL 和 IC 合同测试。"""
    index = pd.date_range("2020-01-01", periods=40, freq="D")
    columns = [f"S{i:02d}" for i in range(20)]
    rng = np.random.default_rng(3)
    base = pd.DataFrame(rng.normal(size=(40, 20)), index=index, columns=columns)
    return {"ret_5d": base, "market_cap": base.abs() + 1, "in_pool": base.notna(),
            "industry": pd.DataFrame("A", index=index, columns=columns)}


def test_dsl_rejects_future_and_evaluates_nan() -> None:
    """DSL 必须拒绝未来标签，并把除零保留为 NaN。"""
    fields = panel()
    with pytest.raises(ValueError):
        compile_expression("raw_5", set(fields))
    result = evaluate("div(ret_5d, sub(ret_5d, ret_5d))", fields)
    assert result.isna().all().all()


def test_ic_translation_invariance_and_holm() -> None:
    """截面平移不改变 IC，Holm 校正保持单调且位于 [0,1]。"""
    fields = panel()
    returns = fields["ret_5d"] * 0.1 + 0.01
    original = daily_ic(fields["ret_5d"], returns, minimum=10)
    assert original.notna().all()
    assert np.allclose(original, daily_ic(fields["ret_5d"], returns + 3, minimum=10))
    adjusted = holm([0.01, 0.02, 0.9])
    assert adjusted[0] <= adjusted[1] <= adjusted[2] <= 1


def test_e_value_contract_and_graph_balance() -> None:
    """同数据 e 值按冻结权重平均，三角形单负边必须发现受挫。"""
    assert np.isclose(merge_e([2, 0.5], [0.5, 0.5]), 1.25)
    assert bet_on_assertion(0.6, {"lower": 0.3, "upper": 0.4}, "hold") > 1
    graph = balance_check(["a", "b", "c"], [
        {"source": "a", "target": "b", "sign": 1},
        {"source": "b", "target": "c", "sign": 1},
        {"source": "a", "target": "c", "sign": -1},
    ])
    assert not graph["balanced"] and graph["cycles"]


def test_map_size_and_audit_immutability(tmp_path: Path) -> None:
    """地图固定 70 格；冻结文件被修改时链校验必须失败。"""
    assert len(build_map()) == 70
    store = AuditStore(tmp_path)
    store.freeze("run", {"id": "S-1"}, {"P1": {"probability": 0.6}})
    frozen = tmp_path / "run" / "S-1" / "frozen.json"
    content = json.loads(frozen.read_text(encoding="utf-8"))
    content["structure"]["id"] = "tampered"
    frozen.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError):
        store.verify()


def test_labels_use_next_open_and_calendar() -> None:
    """收益起点必须为次日开盘，缺失交易日不能由股票级 shift 跳过。"""
    from engine.data import build_labels

    prices = pd.DataFrame({"A": [10., 20., 30., 40., 50.]}, index=pd.bdate_range("2020-01-01", periods=5))
    fields = {"open": prices, "adjustment": prices * 0 + 1,
              "not_suspended": prices.notna(), "in_pool": prices.notna(),
              "industry": prices.astype(str).map(lambda _: "industry")}
    labels = build_labels(fields)
    assert labels["raw_1"].iloc[0, 0] == pytest.approx(0.5)
    fields["not_suspended"].iloc[2, 0] = False
    assert np.isnan(build_labels(fields)["raw_1"].iloc[0, 0])


def test_execution_marks_overnight_and_blocks_exit() -> None:
    """持仓跨夜涨幅进入净值，到期跌停必须抛错，不能静默续持。"""
    from engine.portfolio import ExecutionConfig, execute_long_only

    dates = pd.bdate_range("2020-01-01", periods=5)
    prices = pd.DataFrame({"A": [10., 10., 20., 20., 20.]}, index=dates)
    bars = {"open": prices, "close": prices, "volume": prices * 0 + 1e8,
            "total_turnover": prices * 1e8, "not_suspended": prices.notna(),
            "limit_up": prices * 2, "limit_down": prices / 2}
    target = prices * 0 + 1
    config = ExecutionConfig(holding_days=1, max_positions=1, max_weight=1,
                             min_cash=0, commission_bp=0, slippage_bp=0, stamp_tax_bp=0)
    result = execute_long_only(target, bars, config)
    assert result["cumulative_return"] == pytest.approx(1.0)
    bars["limit_down"] = prices.copy()
    with pytest.raises(RuntimeError, match="到期卖出"):
        execute_long_only(target, bars, config)


def test_confirm_access_is_single_use(tmp_path: Path) -> None:
    """确认凭证跨运行只消费一次，确认后新冻结也必须阻断。"""
    store = AuditStore(tmp_path)
    store.freeze("run", {"id": "S-1"}, {})
    store.consume("B", "run", ["S-1"])
    with pytest.raises(ValueError):
        store.consume("B", "run", ["S-1"])
    with pytest.raises(ValueError):
        store.freeze("next", {"id": "S-2"}, {})
