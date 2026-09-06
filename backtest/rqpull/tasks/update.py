from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from ..config import CHUNK_SIZE, STATE_ROOT, STD_ROOT
from ..io import atomic_parquet, normalize_frame, write_partition_metadata
from ..quota import guard
from ..retry import call_with_retry
from ..warehouse import build_views
from .common import chunks, universe_for_period


def _ready(result) -> bool:
    if isinstance(result, bool):
        return result
    if hasattr(result, "columns") and "ready" in result.columns:
        return bool(result["ready"].all())
    if isinstance(result, dict) and "ready" in result:
        return bool(result["ready"])
    return "True" in str(result)


def _upsert_year(frame: pd.DataFrame, year: int) -> Path:
    target = STD_ROOT / "daily_bar" / f"year={year}" / "data.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    incoming = STATE_ROOT / f"daily_update_{year}.parquet"
    atomic_parquet(frame, incoming)
    temp = target.with_name(".data.parquet.update")
    con = duckdb.connect()
    try:
        incoming_sql = str(incoming).replace("'", "''")
        if target.exists():
            target_sql = str(target).replace("'", "''")
            source = (
                f"SELECT *, 1 AS _priority FROM read_parquet('{target_sql}') "
                f"UNION ALL SELECT *, 2 AS _priority FROM read_parquet('{incoming_sql}')"
            )
        else:
            source = f"SELECT *, 2 AS _priority FROM read_parquet('{incoming_sql}')"
        con.execute(
            f"COPY (SELECT * EXCLUDE(_priority) FROM ({source}) "
            "QUALIFY row_number() OVER (PARTITION BY date, order_book_id ORDER BY _priority DESC)=1 "
            "ORDER BY date, order_book_id) "
            f"TO '{str(temp).replace("'", "''")}' (FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 3)"
        )
    finally:
        con.close()
    os.replace(temp, target)
    incoming.unlink(missing_ok=True)
    write_partition_metadata("daily_bar", target, ("date", "order_book_id"))
    return target


def run(rq) -> dict:
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    calendar = list(rq.get_trading_dates(today - timedelta(days=14), today))
    if not calendar:
        return {"status": "NO_TRADING_DATE"}
    expected = pd.Timestamp(calendar[-1]).date()
    readiness = rq.is_data_ready(categories="stock_daybar", expected_date=int(expected.strftime("%Y%m%d")))
    if not _ready(readiness):
        return {"status": "NOT_READY", "expected_date": str(expected)}
    dates = [pd.Timestamp(d).date() for d in calendar[-5:]]
    start, end = str(dates[0]), str(dates[-1])
    ids = universe_for_period(start, end)
    pieces = []
    for index, group in enumerate(chunks(ids, CHUNK_SIZE)):
        guard(rq, task=f"daily_update:{end}#{index:03d}")
        pieces.append(normalize_frame(call_with_retry(
            rq.get_price, group, start, end, frequency="1d", adjust_type="none",
            skip_suspended=False, expect_df=True,
        )))
    update = pd.concat([p for p in pieces if not p.empty], ignore_index=True)
    paths = []
    for year, part in update.groupby(update["date"].dt.year):
        paths.append(str(_upsert_year(part, int(year))))
    build_views()
    return {"status": "UPDATED", "start": start, "end": end, "rows": len(update), "partitions": paths}

