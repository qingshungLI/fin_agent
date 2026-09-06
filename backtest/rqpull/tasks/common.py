from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

import pandas as pd

from ..config import STD_ROOT


def chunks(values: Sequence[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def load_instruments() -> pd.DataFrame:
    path = STD_ROOT / "instruments.parquet"
    if not path.exists():
        raise RuntimeError("缺少 std/instruments.parquet，请先运行 skeleton")
    return pd.read_parquet(path)


def _date_series(frame: pd.DataFrame, candidates: tuple[str, ...], fallback: str) -> pd.Series:
    for name in candidates:
        if name in frame.columns:
            series = pd.to_datetime(frame[name], errors="coerce")
            return series.fillna(pd.Timestamp(fallback))
    return pd.Series(pd.Timestamp(fallback), index=frame.index)


def universe_for_period(start: str, end: str) -> list[str]:
    instruments = load_instruments()
    listed = _date_series(instruments, ("listed_date", "listed_datetime"), "1900-01-01")
    # pandas 纳秒时间戳上限约为 2262-04-11；用该日期表示仍在上市。
    delisted = _date_series(instruments, ("de_listed_date", "delisted_date"), "2262-04-11")
    mask = (listed <= pd.Timestamp(end)) & (delisted >= pd.Timestamp(start))
    return sorted(instruments.loc[mask, "order_book_id"].dropna().astype(str).unique())


def month_end_trading_dates(start: str, end: str) -> list[pd.Timestamp]:
    calendar = pd.read_parquet(STD_ROOT / "trading_calendar.parquet")
    column = "date" if "date" in calendar.columns else calendar.columns[0]
    dates = pd.to_datetime(calendar[column])
    dates = dates[(dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))]
    return dates.groupby(dates.dt.to_period("M")).max().tolist()
