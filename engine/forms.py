"""Form-specific operationalization contracts built only from registered inputs.

The seven forms remain distinct. Conditional/event signals are masked by coverage,
so inactive observations have no opinion (NaN), never a fabricated zero signal.
"""
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictInt

from engine.dsl import compile_expression

BASE_FIELDS = {
    "ret_1d", "ret_3d", "ret_5d", "ret_20d", "turnover_today", "avg_trade_size",
    "gap_open", "ret_intraday", "realized_vol", "amihud", "auction_imbalance",
    "auction_turnover_share", "dist_52w_high",
}
FAMILY_FIELDS = {
    "M1": {"ret_1d", "turnover_today", "avg_trade_size"},
    "M2": {"ret_1d", "ret_3d", "ret_5d", "amihud"},
    "M3": {"dist_52w_high", "turnover_today"},
    "M4": {"ret_1d", "ret_5d", "turnover_today"},
    "M5": {"ret_1d", "ret_intraday", "gap_open"},
    "M6": set(),  # Index observation fields require their own PIT registration.
    "M7": {"avg_trade_size", "ret_5d"},
    "M9": {"ret_1d", "gap_open"},
    "M10": {"gap_open", "ret_intraday", "auction_imbalance", "auction_turnover_share"},
}
MODERATORS = {
    "market_cap_pct", "amihud_pct", "realized_vol_pct", "auction_spread_pct",
    "turnover_today_pct", "avg_trade_size_pct",
}
EVENTS = {
    "failed_limit_up": "failed_limit_up",
    "return_shock": "abs(ts_z(ret_1d, 60)) > 3",
    "turnover_shock": "ts_z(turnover_today, 60) > 3",
    "gap_shock": "abs(ts_z(gap_open, 60)) > 3",
    "resumption": "not_suspended and (lag(not_suspended, 1) == False)",
}
EVENT_FAMILIES = {
    "M1": ["turnover_shock"], "M2": ["return_shock"],
    "M3": ["return_shock"], "M4": ["return_shock"],
    "M5": ["failed_limit_up", "resumption"], "M6": [],
    "M9": ["resumption"], "M10": ["gap_shock"],
}


class OperationalPlan(BaseModel):
    """No arbitrary expressions, numerical cut selection or outcomes from the model."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    base_field: str
    direction: StrictInt
    pair_field: str | None = None
    moderator: str | None = None
    cut_id: str | None = None
    event: str | None = None


def form_contract(form: int, fields: set[str], cuts: dict[str, Any], family: str) -> dict[str, Any]:
    if form not in range(1, 8):
        raise ValueError("Unknown representation form")
    events = {}
    for name in EVENT_FAMILIES.get(family, []):
        try:
            compile_expression(EVENTS[name], fields, cuts)
        except ValueError:
            continue
        events[name] = EVENTS[name]
    return {
        "form": form, "base_fields": sorted(fields & FAMILY_FIELDS.get(family, BASE_FIELDS)),
        "pair_fields": sorted(fields & BASE_FIELDS),
        "pair_required": form == 5,
        "condition_required": form == 6,
        "allowed_cuts": {key: {"field": row["field"], "side": row["side"]}
                         for key, row in cuts.items() if row["field"] in MODERATORS} if form == 6 else {},
        "event_required": form == 7, "allowed_events": events if form == 7 else {},
        "information": "T close information only; cut IDs frozen using A features, no outcomes",
    }


def compile_form(form: int, plan: OperationalPlan, fields: set[str],
                 cuts: dict[str, Any], family: str) -> dict[str, Any]:
    contract = form_contract(form, fields, cuts, family)
    x = plan.base_field
    if x not in contract["base_fields"] or type(plan.direction) is not int or plan.direction not in (-1, 1):
        raise ValueError("Invalid registered base field or direction")
    if form != 5 and plan.pair_field is not None:
        raise ValueError("Only divergence uses a second measurement")
    if form != 6 and (plan.moderator is not None or plan.cut_id is not None):
        raise ValueError("Only conditional form can select a cut")
    if form != 7 and plan.event is not None:
        raise ValueError("Only event form can select an event")
    level = [f"xs_rank({x})", f"xs_z({x})", f"xs_rank(ts_mean({x}, 3))"]
    coverage = "in_pool"
    event_expression = None
    if form == 1:
        expressions = level
    elif form == 2:
        expressions = [f"xs_rank(diff({x}, 1))", f"xs_z(diff({x}, 1))",
                       f"xs_rank(diff(ts_mean({x}, 3), 1))"]
    elif form == 3:
        expressions = [f"ts_z({x}, 20)", f"ts_z({x}, 60)",
                       f"xs_rank(sub({x}, ts_mean({x}, 20)))"]
    elif form == 4:
        centered = f"sub({x}, industry_mean({x}))"
        smoothed = f"ts_mean({x}, 3)"
        expressions = [f"xs_rank({centered})", f"xs_z({centered})",
                       f"xs_rank(sub({smoothed}, industry_mean({smoothed})))"]
    elif form == 5:
        y = plan.pair_field
        if y not in contract["pair_fields"] or x == y:
            raise ValueError("Divergence requires two distinct registered measurements")
        expressions = [f"sub(xs_rank({x}), xs_rank({y}))",
                       f"sub(xs_z({x}), xs_z({y}))",
                       f"sub(ts_z({x}, 20), ts_z({y}, 20))"]
    elif form == 6:
        cut = contract["allowed_cuts"].get(plan.cut_id)
        if cut is None or cut["field"] != plan.moderator or plan.moderator.removesuffix("_pct") == x:
            raise ValueError("Condition must use an independent moderator and its frozen cut")
        coverage += f' and (gate({plan.moderator}, "{plan.cut_id}") == 1)'
        expressions = level
    else:
        event_expression = contract["allowed_events"].get(plan.event)
        if event_expression is None:
            raise ValueError("Event is unavailable for this mechanism and data contract")
        coverage += f" and ({event_expression})"
        expressions = level
    expressions = [f"neg({expr})" if plan.direction == -1 else expr for expr in expressions]
    for expression in [*expressions, coverage]:
        compile_expression(expression, fields, cuts)
    return {"operational": expressions, "coverage": coverage, "plan": plan.model_dump(),
            "event_expression": event_expression, "form_contract": contract}
