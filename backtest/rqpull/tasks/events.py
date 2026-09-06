from __future__ import annotations

import pandas as pd

from ..config import CHUNK_SIZE, END_DATE, MARKET_START
from ..io import merge_partition, normalize_frame, stage_write
from ..quota import guard
from ..retry import call_with_retry
from ..state import Manifest
from .common import chunks, universe_for_period


EVENTS = {
    "dividend": ("get_dividend", ("declaration_announcement_date", "order_book_id", "quarter"), None),
    "split": ("get_split", ("ex_dividend_date", "order_book_id"), None),
    "adj_factor": ("get_ex_factor", ("ex_date", "order_book_id"), None),
    "st_flag": ("is_st_stock", ("date", "order_book_id"), "is_st"),
    "suspension": ("is_suspended", ("date", "order_book_id"), "is_suspended"),
}


def _wide_flag_to_long(frame, value_name: str) -> pd.DataFrame:
    frame = normalize_frame(frame)
    if frame.empty:
        return frame
    if "order_book_id" in frame.columns and value_name in frame.columns:
        return frame
    if "date" not in frame.columns:
        raise ValueError(f"{value_name} 返回结构缺少 date")
    stock_columns = [c for c in frame.columns if c != "date"]
    return frame.melt(id_vars=["date"], value_vars=stock_columns, var_name="order_book_id", value_name=value_name)


def run(rq, manifest: Manifest, start: str = MARKET_START, end: str = END_DATE) -> None:
    for task, (api_name, primary_key, flag_name) in EVENTS.items():
        api = getattr(rq, api_name)
        manifest.set_status(task, "RUNNING")
        for year in range(int(start[:4]), int(end[:4]) + 1):
            year_start = max(start, f"{year}-01-01")
            year_end = min(end, f"{year}-12-31")
            ids = universe_for_period(year_start, year_end)
            groups = list(chunks(ids, CHUNK_SIZE))
            for index, group in enumerate(groups):
                chunk_id = f"{year}#{index:03d}"
                if manifest.is_done(task, chunk_id):
                    continue
                guard(rq, task=f"{task}:{chunk_id}")
                frame = call_with_retry(api, group, year_start, year_end)
                if flag_name:
                    frame = _wide_flag_to_long(frame, flag_name)
                stage_write(frame, task, chunk_id, year=year)
                manifest.mark_chunk_done(task, chunk_id)
            if all(manifest.is_done(task, f"{year}#{i:03d}") for i in range(len(groups))):
                merge_partition(task, year, primary_key)
        manifest.set_status(task, "COMPLETE")

