"""扩展字段管线：从历史行情、估值和完整指数快照生成可搜索代理，不读取未来收益。

指数快照在下一交易日才视为可观察，保留最近已知快照而非伪造实时权重；超过
45 个日历日不再沿用。约束强度按当日涨跌停带宽归一化，不把二元状态当连续强度。
"""

from typing import Mapping

import numpy as np
import pandas as pd


def observed_index_fields(
    snapshots: Mapping[str, pd.DataFrame], dates: pd.DatetimeIndex, symbols: pd.Index,
) -> dict[str, pd.DataFrame]:
    """对齐最近已知指数快照及月度观察变化。

    Args:
        snapshots: 按指数区分的完整权重表，列为 snapshot_date/order_book_id/weight。
        dates: 严格递增的交易日历。
        symbols: 输出股票索引；快照完整性校验在筛选股票前完成。
    Returns:
        dict[str, pd.DataFrame]: 已知权重、已知权重变化和观察事件；未知保持 NaN。
    """
    if not snapshots or dates.empty or symbols.empty or not dates.is_unique or not dates.is_monotonic_increasing:
        raise ValueError("指数快照、日期、股票不能为空，交易日必须严格递增")
    levels, changes, events = [], [], []
    for name, table in snapshots.items():
        if table.empty or table.duplicated(["snapshot_date", "order_book_id"]).any():
            raise ValueError(f"{name}: 空快照或重复股票主键")
        if table[["snapshot_date", "order_book_id", "weight"]].isna().any().any():
            raise ValueError(f"{name}: 快照主键或权重缺失")
        if not np.isfinite(table.weight).all() or (table.weight < 0).any():
            raise ValueError(f"{name}: 权重必须非负且有限")
        totals = table.groupby("snapshot_date").weight.sum()
        # 允许供应商四舍五入累计误差 2%；不完整快照不能将缺失成员当成零权重。
        if not totals.between(0.98, 1.02).all():
            raise ValueError(f"{name}: 完整快照权重和必须接近 1")
        wide = table.pivot(index="snapshot_date", columns="order_book_id", values="weight").sort_index()
        wide = wide.reindex(columns=symbols).fillna(0.0)
        delta = wide.diff()
        position = dates.searchsorted(pd.DatetimeIndex(wide.index), side="right")
        usable = position < len(dates)
        wide, delta = wide.loc[usable].copy(), delta.loc[usable].copy()
        position = position[usable]
        if len(position) == 0:
            raise ValueError(f"{name}: 无可观察快照")
        if len(np.unique(position)) != len(position):
            raise ValueError(f"{name}: 多个快照映射到同一观察日")
        available = dates[position]
        wide.index = delta.index = available
        last_seen = pd.Series(available, index=available).reindex(dates).ffill()
        fresh = (pd.Series(dates, index=dates) - last_seen).dt.days.le(45)
        levels.append(wide.reindex(dates).ffill().where(fresh, axis=0))
        changes.append(delta.reindex(dates).ffill().where(fresh, axis=0))
        event = pd.DataFrame(False, index=dates, columns=symbols)
        event.loc[available] = True
        events.append(event)
    level = sum(levels) / len(levels)
    change = sum(changes) / len(changes)
    observed = events[0].copy()
    for event in events[1:]:
        observed |= event
    return {"index_known_weight": level, "index_weight_change": change,
            "index_snapshot_event": observed}


def market_proxy_fields(fields: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """生成连续约束、不确定性和估值代理。

    Args:
        fields: 同索引原始/已计算矩阵，包含价格、涨跌停、收益、估值比率。
    Returns:
        dict[str, pd.DataFrame]: 派生信号；除零和历史不足保留缺失，无未来信息。
    """
    required = {"close", "prev_close", "limit_up", "limit_down", "ret_1d", "pb_ratio_lf", "pe_ratio_ttm"}
    if required - fields.keys():
        raise ValueError(f"缺少派生输入: {sorted(required - fields.keys())}")
    close = fields["close"]
    for name in required:
        if not fields[name].index.equals(close.index) or not fields[name].columns.equals(close.columns):
            raise ValueError(f"字段未对齐: {name}")
    up_band = fields["limit_up"] - fields["prev_close"]
    down_band = fields["prev_close"] - fields["limit_down"]
    valid_band = up_band.gt(0) & down_band.gt(0) & fields["limit_down"].gt(0)
    move = close - fields["prev_close"]
    band = up_band.where(move.ge(0), down_band).where(valid_band)
    pressure = move.div(band)
    returns = fields["ret_1d"]
    volatility = returns.rolling(20, min_periods=20).std()
    historical_vol = volatility.rolling(20, min_periods=20).mean().shift(1)
    uncertainty_change = volatility.div(historical_vol.where(historical_vol.gt(0))) - 1
    # 估值字段额外滞后一日；负估值不取倒数，避免负权益被误当便宜。
    pb = fields["pb_ratio_lf"].shift(1)
    pe = fields["pe_ratio_ttm"].shift(1)
    return {
        "constraint_pressure": pressure,
        "limit_up_distance": (fields["limit_up"] - close).div(up_band.where(valid_band)),
        "uncertainty_level": volatility,
        "uncertainty_change": uncertainty_change,
        "book_to_price": 1 / pb.where(pb.gt(0)),
        "earnings_yield": 1 / pe.where(pe.gt(0)),
        "constraint_event": pressure.abs().gt(0.9) & pressure.shift(1).abs().le(0.9),
        "uncertainty_resolution": uncertainty_change.lt(-0.3) & uncertainty_change.shift(1).ge(-0.3),
    }
