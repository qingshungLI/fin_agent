"""字段回归：验证快照不提前可见、连续约束计算、历史不变性和全部 70 格可构造。"""

import numpy as np
import pandas as pd
import pytest

from engine.catalog import build_map
from engine.cycle import initial_tasks
from engine.forms import BASE_FIELDS, EVENTS, OperationalPlan, compile_form, form_contract
from engine.research_fields import market_proxy_fields, observed_index_fields


def test_snapshot_available_next_day_and_removal_is_zero() -> None:
    """验证快照观察日和剔除权重；无参数，返回 None，使用完整单指数快照。"""
    dates = pd.bdate_range("2020-01-01", periods=50)
    snapshots = pd.DataFrame({"snapshot_date": [dates[1], dates[1], dates[20]],
                              "order_book_id": ["A", "B", "A"], "weight": [0.4, 0.6, 1.0]})
    result = observed_index_fields({"index": snapshots}, dates, pd.Index(["A", "B"]))
    weights = result["index_known_weight"]
    assert weights.loc[dates[1]].isna().all()
    assert weights.loc[dates[2], "A"] == 0.4
    assert weights.loc[dates[20], "B"] == 0.6
    assert weights.loc[dates[21], "B"] == 0
    assert result["index_weight_change"].loc[dates[21], "B"] == -0.6
    short = observed_index_fields({"index": snapshots.iloc[:2]}, dates[:20], pd.Index(["A", "B"]))
    pd.testing.assert_frame_equal(weights.iloc[:20], short["index_known_weight"])
    with pytest.raises(ValueError, match="1"):
        observed_index_fields({"index": snapshots.iloc[:1]}, dates, pd.Index(["A", "B"]))


def test_proxy_fields_preserve_history_and_missing_values() -> None:
    """验证代理因子历史截断和除零；无参数，返回 None，所有数据为受控合成值。"""
    dates = pd.bdate_range("2020-01-01", periods=100)
    rng = np.random.default_rng(2)
    base = pd.DataFrame(10.0, index=dates, columns=["A", "B"])
    fields = {"close": base + 0.5, "prev_close": base, "limit_up": base + 1,
              "limit_down": base - 1, "ret_1d": pd.DataFrame(rng.normal(0, .01, (100, 2)), index=dates, columns=base.columns),
              "pb_ratio_lf": base / 5, "pe_ratio_ttm": base}
    result = market_proxy_fields(fields)
    assert result["constraint_pressure"].iloc[-1, 0] == 0.5
    assert result["book_to_price"].iloc[0].isna().all()
    assert result["book_to_price"].iloc[1, 0] == 0.5
    short = market_proxy_fields({name: frame.iloc[:70] for name, frame in fields.items()})
    for name, frame in short.items():
        pd.testing.assert_frame_equal(frame, result[name].iloc[:70])
    fields["limit_up"] = base
    assert market_proxy_fields(fields)["constraint_pressure"].isna().all().all()


def test_every_grid_cell_has_a_registered_construction() -> None:
    """验证全部 70 格的字段和形式编译；无参数，返回 None，不使用收益结果。"""
    fields = BASE_FIELDS | {"in_pool", "industry", "market_cap_pct", "failed_limit_up",
                            "not_suspended", "constraint_event", "index_snapshot_event", "uncertainty_resolution"}
    cuts = {"cap_low": {"field": "market_cap_pct", "side": "low", "value": 30.0}}
    assert len(initial_tasks()) == 70
    for cell in build_map():
        form, family = cell["form"], cell["family"]
        contract = form_contract(form, fields, cuts, family)
        base = contract["base_fields"][0]
        plan = {"base_field": base, "direction": 1}
        if form == 5:
            plan["pair_field"] = next(name for name in contract["pair_fields"] if name != base)
        elif form == 6:
            plan.update(moderator="market_cap_pct", cut_id="cap_low")
        elif form == 7:
            assert contract["allowed_events"], cell["id"]
            plan["event"] = next(iter(contract["allowed_events"]))
        result = compile_form(form, OperationalPlan(**plan), fields, cuts, family)
        assert len(set(result["operational"])) == 3, cell["id"]
