"""数据管线：按授权日期扫描本地 Parquet，验证主键与业务口径，建立交易日矩阵。

特征只向历史滚动；标签按 T+1 开盘至 T+1+h 开盘生成并在分段边界截断。
行业以精确三级有效区间连接，缺失不填成其他行业；原始文件始终只读。
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from engine.config import HORIZONS, ResearchConfig


@dataclass
class MarketPanel:
    """保存对齐的特征、标签和质量报告；参数为矩阵字典，假设索引完全相同。"""

    fields: dict[str, pd.DataFrame]
    labels: dict[str, pd.DataFrame]
    report: list[dict[str, Any]]
    manifest: list[dict[str, Any]] = field(default_factory=list)

    @property
    def dates(self) -> pd.DatetimeIndex:
        """返回交易日索引；无参数，假设 close 已存在。"""
        return self.fields["close"].index


def source_files(root: Path, name: str, start: str, end: str) -> list[Path]:
    """选择日期覆盖内的实体分区；输入根目录/表/日期，返回文件，排除 AppleDouble。"""
    folder = root / name
    if folder.is_file():
        return [folder]
    files = sorted(folder.rglob("data.parquet"))
    selected = []
    for path in files:
        years = [int(part[5:]) for part in path.parts if part.startswith("year=")]
        if not years or int(start[:4]) <= years[0] <= int(end[:4]):
            selected.append(path)
    if not selected:
        raise FileNotFoundError(f"缺少数据分区: {name} [{start}, {end}]")
    return selected


def read_source(
    root: Path, name: str, start: str, end: str,
    columns: list[str] | None = None, symbols: list[str] | None = None,
    date_column: str | None = "date", manifest: list[dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """按投影和谓词扫描表；返回长表，非日期表必须显式传入 date_column=None。"""
    files = source_files(root, name, start, end)
    dataset = ds.dataset([str(p) for p in files], format="parquet")
    predicate = None
    if date_column:
        predicate = (ds.field(date_column) >= pd.Timestamp(start)) & (
            ds.field(date_column) < pd.Timestamp(end) + pd.Timedelta(days=1)
        )
    if symbols is not None:
        symbol_filter = ds.field("order_book_id").isin(symbols)
        predicate = symbol_filter if predicate is None else predicate & symbol_filter
    result = dataset.to_table(columns=columns, filter=predicate).to_pandas()
    if manifest is not None:
        for path in files:
            stat = path.stat()
            manifest.append({"path": str(path.relative_to(root)), "bytes": stat.st_size,
                             "mtime_ns": stat.st_mtime_ns, "start": start, "end": end,
                             "date_column": date_column, "columns": columns})
    return result


def require_unique(frame: pd.DataFrame, keys: list[str], source: str) -> None:
    """检查主键；输入表及键名，无返回，重复或空主键直接拒绝连接。"""
    bad = frame.duplicated(keys, keep=False) | frame[keys].isna().any(axis=1)
    if bad.any():
        raise ValueError(f"{source} 主键异常: {frame.loc[bad, keys].head(3).to_dict('records')}")


def attach_industry_pit(
    dates: pd.DatetimeIndex, symbols: list[str], changes: pd.DataFrame,
    policy: str = "strict",
) -> pd.DataFrame:
    """Join half-open intervals; conflicting codes remain unknown, never guessed.

    Quarantine is an explicit research-cohort policy. Identical overlapping codes
    can be merged without ambiguity. Invalid intervals always fail.
    """
    if policy not in {"strict", "quarantine"}:
        raise ValueError("Unknown industry policy")
    result = pd.DataFrame(None, index=dates, columns=symbols, dtype=object)
    for symbol, rows in changes.drop_duplicates().groupby("order_book_id", sort=False):
        if symbol not in result:
            continue
        active = np.zeros(len(dates), dtype=np.int32)
        assigned = np.empty(len(dates), dtype=object)
        assigned[:] = None
        for code, intervals in rows.groupby("industry_code"):
            present = np.zeros(len(dates), dtype=bool)
            for row in intervals.itertuples():
                if pd.isna(row.start_date) or pd.isna(row.cancel_date) or row.start_date >= row.cancel_date:
                    raise ValueError(f"行业有效区间反向或缺失: {symbol}")
                present |= (dates >= row.start_date) & (dates < row.cancel_date)
            assigned[present] = code
            active += present
        if (active > 1).any() and policy == "strict":
            raise ValueError(f"行业有效区间重叠或反向: {symbol}")
        assigned[active != 1] = None
        result[symbol] = assigned
    return result



def attach_daily_industry(dates, symbols, daily):
    """Join vendor day-level responses exactly; never infer between observations."""
    required = {"order_book_id", "date", "third_industry_code", "source",
                "client_version", "retrieved_at"}
    if not required <= set(daily.columns):
        raise ValueError("逐日行业缺少来源或日期字段")
    require_unique(daily, ["order_book_id", "date"], "RQData逐日行业")
    if (daily.empty or not daily.source.eq("sws").all()
            or not daily.client_version.eq("3.5.6.1").all()
            or daily.third_industry_code.isna().any()
            or pd.to_datetime(daily.retrieved_at, utc=True, errors="coerce").isna().any()):
        raise ValueError("逐日行业来源、版本或代码无效")
    return daily.pivot(index="date", columns="order_book_id",
                       values="third_industry_code").reindex(index=dates, columns=symbols)


def industry_mean(values: pd.DataFrame, industry: pd.DataFrame) -> pd.DataFrame:
    """Mean per date and known industry with missing values excluded.

    Integer group codes and bincount avoid constructing thousands of DataFrames.
    No cross-day pooling, zero filling, or mixing of unknown industries.
    """
    if not values.index.equals(industry.index) or not values.columns.equals(industry.columns):
        raise ValueError("Industry and value indexes differ")
    array = values.to_numpy(dtype=float)
    codes = industry.to_numpy()
    output = np.full(array.shape, np.nan)
    for day in range(len(array)):
        groups, labels = pd.factorize(codes[day], sort=False)
        valid = (groups >= 0) & np.isfinite(array[day])
        sums = np.bincount(groups[valid], weights=array[day, valid], minlength=len(labels))
        counts = np.bincount(groups[valid], minlength=len(labels))
        means = np.divide(sums, counts, out=np.full(len(labels), np.nan), where=counts > 0)
        known = groups >= 0
        output[day, known] = means[groups[known]]
    return pd.DataFrame(output, index=values.index, columns=values.columns)


def build_labels(fields: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """构造 T+1 开盘收益四周期口径；返回标签，日历缺行和窗口停牌不跨越。"""
    adjusted_open = fields["open"] * fields["adjustment"]
    tradable = fields["not_suspended"] & fields["open"].gt(0)
    labels = {}
    for horizon in HORIZONS:
        valid_window = tradable.shift(-1, fill_value=False)
        for offset in range(2, horizon + 2):
            valid_window &= tradable.shift(-offset, fill_value=False)
        raw = (adjusted_open.shift(-horizon - 1) / adjusted_open.shift(-1) - 1)
        raw = raw.where(valid_window & fields["in_pool"])
        labels[f"raw_{horizon}"] = raw
        labels[f"market_excess_{horizon}"] = raw.sub(raw.mean(axis=1), axis=0)
        labels[f"industry_resid_{horizon}"] = raw - industry_mean(raw, fields["industry"])
    return labels


def build_panel(
    root: Path, config: ResearchConfig, start: str | None = None, end: str | None = None,
) -> MarketPanel:
    """读取指定授权区间并验证矩阵；返回面板，调用者负责 B/H 一次性访问授权。"""
    start, end = start or config.start, end or config.end
    warmup = max("2016-07-01", str((pd.Timestamp(start) - pd.Timedelta(days=420)).date()))
    report: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []
    calendar = pq.read_table(root / "trading_calendar.parquet").to_pandas()["date"]
    calendar = pd.DatetimeIndex(pd.to_datetime(calendar)).sort_values()
    if calendar.has_duplicates:
        raise ValueError("交易日历包含重复日期")
    dates = calendar[(calendar >= warmup) & (calendar <= end)]
    instruments = pq.read_table(root / "instruments.parquet").to_pandas()
    require_unique(instruments, ["order_book_id"], "instruments")
    # 抽样按代码哈希固定，保留退市证券，绝不依据收益或当前存续状态选股。
    symbols = sorted(instruments.order_book_id.tolist(), key=lambda s: hashlib.sha256(s.encode()).hexdigest())
    if config.max_symbols:
        symbols = symbols[:config.max_symbols]
    symbols = sorted(symbols)
    bars = read_source(root, "daily_bar", warmup, end, symbols=symbols, manifest=manifest)
    require_unique(bars, ["order_book_id", "date"], "daily_bar")
    if bars.empty or not pd.DatetimeIndex(bars.date).isin(calendar).all():
        raise ValueError("行情为空或包含非交易日期")
    numeric = ["open", "high", "low", "close", "volume", "total_turnover", "num_trades"]
    if not np.isfinite(bars[numeric].to_numpy()).all() or (bars[numeric] < 0).any().any():
        raise ValueError("行情包含负数、缺失或无穷值")
    active = bars.volume > 0
    bad_ohlc = (bars.high < bars[["open", "close", "low"]].max(axis=1) - 1e-8) | (
        bars.low > bars[["open", "close", "high"]].min(axis=1) + 1e-8
    )
    if (bad_ohlc & active).any():
        raise ValueError("OHLC 高低价约束失败")
    fields = {name: bars.pivot(index="date", columns="order_book_id", values=name).reindex(
        index=dates, columns=symbols) for name in numeric + ["prev_close", "limit_up", "limit_down"]}
    report.append({"name": "行情主键 / 交易日 / OHLC", "status": "pass", "count": len(bars)})
    vwap = bars.total_turnover.div(bars.volume.replace(0, np.nan))
    scale_bad = active & ((vwap < bars.low * 0.8) | (vwap > bars.high * 1.2))
    if scale_bad.mean() > 0.01:
        raise ValueError("成交额/成交量单位量级校验失败，异常超过 1%")
    report.append({"name": "成交量额单位量级", "status": "warning" if scale_bad.any() else "pass",
                   "count": int(scale_bad.sum())})
    for source, column, target in [("st_flag", "is_st", "not_st"),
                                   ("suspension", "is_suspended", "not_suspended"),
                                   ("turnover", "today", "turnover_today"),
                                   ("valuation", "market_cap", "market_cap")]:
        table = read_source(root, source, warmup, end, ["order_book_id", "date", column], symbols, manifest=manifest)
        require_unique(table, ["order_book_id", "date"], source)
        matrix = table.pivot(index="date", columns="order_book_id", values=column).reindex(index=dates, columns=symbols)
        missing = matrix.isna() & fields["close"].notna()
        if source in ("st_flag", "suspension"):
            if missing.any().any():
                raise ValueError(f"{source} 缺少行情对应状态，不能默认可交易")
            fields[target] = matrix.eq(False)
        else:
            fields[target] = matrix / 100 if source == "turnover" else matrix
        report.append({"name": source + " 唯一连接", "status": "warning" if missing.any().any() else "pass",
                       "count": int(missing.sum().sum())})
    instruments = instruments.set_index("order_book_id").reindex(symbols)
    listed = pd.to_datetime(instruments.listed_date)
    listed_positions = calendar.searchsorted(listed)
    ages = calendar.searchsorted(dates).to_numpy() if hasattr(calendar.searchsorted(dates), "to_numpy") else calendar.searchsorted(dates)
    age = ages[:, None] - listed_positions[None, :]
    prehistory = listed < calendar[0] - pd.Timedelta(days=240)
    age[:, prehistory.to_numpy()] += 120
    fields["days_since_listing"] = pd.DataFrame(age, index=dates, columns=symbols)
    delisted = pd.to_datetime(instruments.de_listed_date, errors="coerce")
    fields["not_delisted"] = pd.DataFrame(
        (dates.to_numpy()[:, None] < delisted.to_numpy()[None, :]) | delisted.isna().to_numpy()[None, :],
        index=dates, columns=symbols)
    fields["listed_ok"] = fields["days_since_listing"].ge(120)
    fields["in_pool"] = (fields["listed_ok"] & fields["not_delisted"] & fields["not_st"]
                         & fields["not_suspended"] & fields["close"].gt(0))
    if config.industry_source == "rqdata_daily":
        daily = read_source(root, "industry_sws_daily", warmup, end,
                            symbols=symbols, manifest=manifest)
        fields["industry"] = attach_daily_industry(dates, symbols, daily)
        report.append({"name": "RQData逐交易日三级行业直接查询", "status": "pass",
                       "count": len(daily), "source": "sws", "client_version": "3.5.6.1",
                       "detail": "按历史有效日直接查询；未由月度快照前填/后填。属于当前供应商历史响应，不冒充历史发布时点存档。"})
    else:
        changes = read_source(root, "industry_sws_2021_exact_changes", warmup, end,
                              symbols=symbols, date_column=None, manifest=manifest)
        fields["industry"] = attach_industry_pit(dates, symbols, changes, config.industry_policy)
    unknown = fields["industry"].isna() & fields["in_pool"]
    unknown_fraction = float(unknown.sum().sum() / max(1, fields["in_pool"].sum().sum()))
    if config.industry_policy == "strict" and unknown_fraction > 0.01:
        raise ValueError(f"PIT 行业空档率 {unknown_fraction:.2%} > 1%")
    report.append({"name": "PIT 精确三级行业（非一级）", "status": "warning" if unknown_fraction else "pass",
                   "count": int(unknown.sum().sum())})
    if config.industry_policy == "quarantine":
        before = int(fields["in_pool"].sum().sum())
        fields["in_pool"] &= fields["industry"].notna()
        report.append({"name": "显式隔离未知或歧义行业观测", "status": "warning",
                       "count": int(unknown.sum().sum()), "fraction": unknown_fraction,
                       "eligible_before": before, "policy": "quarantine",
                       "formal_eligible": False,
                       "detail": "原始数据未修改；结果只适用于已知行业研究子集，不可授予正式 PASS"})
    adjustments = read_source(root, "adj_factor", "2016-07-01", end,
                              symbols=symbols, date_column="ex_date", manifest=manifest)
    require_unique(adjustments, ["order_book_id", "ex_date"], "adj_factor")
    if (adjustments.ex_factor <= 0).any() or not np.isfinite(adjustments.ex_factor).all():
        raise ValueError("复权事件因子必须为正有限数")
    if (adjustments.announcement_date > adjustments.ex_date).any():
        raise ValueError("复权事件公告晚于生效日，PIT 可得性无法确认")
    factor_dates = calendar[calendar <= end]
    event_factor = adjustments.pivot(index="ex_date", columns="order_book_id", values="ex_factor")
    fields["adjustment"] = event_factor.reindex(index=factor_dates, columns=symbols).fillna(1).cumprod().reindex(dates)
    adjusted_close = fields["close"] * fields["adjustment"]
    fields["adj_close"] = adjusted_close
    fields["ret_1d"] = adjusted_close.pct_change(fill_method=None)
    fields["ret_3d"] = adjusted_close.pct_change(3, fill_method=None)
    fields["ret_5d"] = adjusted_close.pct_change(5, fill_method=None)
    fields["ret_20d"] = adjusted_close.pct_change(20, fill_method=None)
    reference = fields["close"].div(fields["prev_close"]) - 1
    event_mask = event_factor.reindex(index=dates, columns=symbols).notna()
    errors = (fields["ret_1d"] - reference).abs().where(event_mask & fields["not_suspended"])
    compared = errors.stack()
    if compared.empty or float((compared > 0.003).mean()) > 0.01:
        raise ValueError("复权方向/除权日参考收益校验失败或无可验证事件")
    report.append({"name": "复权事件与参考昨收校准", "status": "pass", "count": len(compared),
                   "max_error": float(compared.max())})
    calibration = read_source(root, "return_calibration", warmup, end, symbols=symbols, manifest=manifest)
    require_unique(calibration, ["order_book_id", "date"], "return_calibration")
    official = calibration.pivot(index="date", columns="order_book_id", values="official_return").reindex(index=dates, columns=symbols)
    official_error = (reference - official).abs().stack()
    if official_error.empty or (official_error > 0.003).mean() > 0.01:
        raise ValueError("官方抽样收益校准失败")
    report.append({"name": "官方收益抽样校准（不作为标签）", "status": "pass", "count": len(official_error)})
    fields["realized_vol"] = fields["ret_1d"].rolling(20, min_periods=20).std()
    fields["amihud"] = fields["ret_1d"].abs().div(fields["total_turnover"].replace(0, np.nan)).rolling(20, min_periods=20).mean()
    fields["avg_trade_size"] = fields["total_turnover"].div(fields["num_trades"].replace(0, np.nan))
    fields["gap_open"] = fields["open"].div(fields["prev_close"].replace(0, np.nan)) - 1
    fields["ret_intraday"] = fields["close"].div(fields["open"].replace(0, np.nan)) - 1
    fields["dist_52w_high"] = adjusted_close / (fields["high"] * fields["adjustment"]).rolling(252, min_periods=252).max()
    fields["is_limit_up"] = fields["close"].ge(fields["limit_up"] - 0.005) & fields["limit_up"].gt(0)
    fields["is_limit_down"] = fields["close"].le(fields["limit_down"] + 0.005) & fields["limit_down"].gt(0)
    fields["failed_limit_up"] = fields["high"].ge(fields["limit_up"] - 0.005) & ~fields["is_limit_up"] & fields["limit_up"].gt(0)
    if config.data_profile == "full":
        auction = read_source(root, "open_auction", warmup, end, symbols=symbols,
                              date_column="datetime", manifest=manifest)
        auction["date"] = pd.to_datetime(auction.datetime).dt.normalize()
        require_unique(auction, ["order_book_id", "date"], "open_auction")
        seconds = (pd.to_datetime(auction.datetime) - auction.date).dt.total_seconds()
        outside = (seconds < 9 * 3600 + 24 * 60) | (seconds > 9 * 3600 + 26 * 60)
        if outside.any():
            if (config.auction_policy or config.industry_policy) == "strict":
                raise ValueError("竞价快照不在约定 09:24-09:26 窗口")
            report.append({"name": "隔离超时竞价快照", "status": "warning",
                           "count": int(outside.sum()), "formal_eligible": False,
                           "detail": "未将其他时点盘口冒充竞价；所有对应竞价字段保留缺失"})
            auction.loc[outside, [c for c in auction.columns if c not in
                                 {"order_book_id", "datetime", "date"}]] = np.nan
        buy = auction[[f"b{i}_v" for i in range(1, 6)]].sum(axis=1, min_count=5)
        sell = auction[[f"a{i}_v" for i in range(1, 6)]].sum(axis=1, min_count=5)
        auction["auction_imbalance"] = (buy - sell) / (buy + sell).replace(0, np.nan)
        valid_quote = auction.a1.gt(0) & auction.b1.gt(0) & auction.a1.ge(auction.b1)
        auction["auction_spread"] = ((auction.a1 - auction.b1) / ((auction.a1 + auction.b1) / 2)).where(valid_quote)
        auction["auction_amount"] = auction.total_turnover
        for name in ["auction_imbalance", "auction_spread", "auction_amount"]:
            fields[name] = auction.pivot(index="date", columns="order_book_id", values=name).reindex(index=dates, columns=symbols)
        fields["auction_turnover_share"] = fields["auction_amount"] / fields["total_turnover"].rolling(20, min_periods=20).mean().shift(1)
        report.append({"name": "竞价盘口有效性", "status": "warning" if not valid_quote.all() else "pass",
                       "count": int((~valid_quote).sum()), "detail": "零价或交叉盘口不作为可用价差"})
    else:
        report.append({"name": "事前登记日线量价数据配置", "status": "pass", "count": 0,
                       "detail": "不读取或登记任何竞价字段，不能据此研究竞价机制"})
    for name in ["market_cap", "amihud", "realized_vol", "auction_spread", "turnover_today", "avg_trade_size"]:
        if name in fields:
            fields[name + "_pct"] = fields[name].where(fields["in_pool"]).rank(axis=1, pct=True) * 100
    from engine.research_fields import market_proxy_fields, observed_index_fields

    valuation = read_source(root, "valuation", warmup, end,
                            ["order_book_id", "date", "pb_ratio_lf", "pe_ratio_ttm"],
                            symbols, manifest=manifest)
    require_unique(valuation, ["order_book_id", "date"], "valuation proxies")
    for name in ["pb_ratio_lf", "pe_ratio_ttm"]:
        fields[name] = valuation.pivot(index="date", columns="order_book_id", values=name).reindex(
            index=dates, columns=symbols)
    fields.update(market_proxy_fields(fields))
    snapshots = {
        index: read_source(root, f"index_weights_{index}", warmup, end,
                           ["order_book_id", "snapshot_date", "weight"],
                           date_column="snapshot_date", manifest=manifest)
        for index in ["000300_XSHG", "000905_XSHG", "000852_XSHG"]
    }
    fields.update(observed_index_fields(snapshots, dates, pd.Index(symbols)))
    report.append({"name": "扩展机制代理字段", "status": "pass", "count": 11,
                   "detail": "指数为下一交易日起的最近已知快照；估值滞后一日；不确定性为量价代理。M8仅检验短期重定价，不推断长期风险溢价。"})
    labels = build_labels(fields)
    for name, values in list(labels.items()):
        if name.startswith("raw_"):
            labels[name.replace("raw_", "net_")] = values - (2 * config.commission_bp + 2 * config.slippage_bp + config.stamp_tax_bp) / 10000
    # 暖启动行只供特征计算，标签与最终暴露面板都裁到授权研究区间。
    selection = (dates >= start) & (dates <= end)
    fields = {key: value.loc[selection] for key, value in fields.items()}
    labels = {key: value.loc[selection] for key, value in labels.items()}
    return MarketPanel(fields, labels, report, manifest)
