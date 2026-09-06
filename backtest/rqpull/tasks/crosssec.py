from __future__ import annotations

import pandas as pd

from ..config import CHUNK_SIZE, END_DATE, INDEXES, MARKET_START, STD_ROOT, VALUATION_FACTORS
from ..io import atomic_parquet, merge_partition, normalize_frame, stage_write
from ..quota import guard
from ..retry import call_with_retry
from ..state import Manifest
from .common import chunks, month_end_trading_dates, universe_for_period


def _probe_factors(rq, probe_id: str) -> list[str]:
    valid = []
    for factor in VALUATION_FACTORS:
        try:
            result = rq.get_factor([probe_id], factor, "2021-03-01", "2021-03-03")
            if result is not None:
                valid.append(factor)
        except Exception:
            continue
    return valid


def run(rq, manifest: Manifest, start: str = MARKET_START, end: str = END_DATE) -> None:
    month_ends = month_end_trading_dates(start, end)

    # 基准指数日线：按年存储，避免与个股日线混表。
    task = "index_daily_bar"
    manifest.set_status(task, "RUNNING")
    for year in range(int(start[:4]), int(end[:4]) + 1):
        chunk_id = str(year)
        if manifest.is_done(task, chunk_id):
            continue
        ys, ye = max(start, f"{year}-01-01"), min(end, f"{year}-12-31")
        guard(rq, task=f"{task}:{chunk_id}")
        frame = call_with_retry(
            rq.get_price, list(INDEXES), ys, ye, frequency="1d",
            adjust_type="none", skip_suspended=False, expect_df=True,
        )
        stage_write(frame, task, chunk_id, year=year)
        manifest.mark_chunk_done(task, chunk_id)
        merge_partition(task, year, ("date", "order_book_id"))
    manifest.set_status(task, "COMPLETE")

    for source, task in (("citics_2019", "industry_citics"), ("sws", "industry_sws")):
        manifest.set_status(task, "RUNNING")
        for snapshot in month_ends:
            chunk_id = snapshot.strftime("%Y-%m")
            if manifest.is_done(task, chunk_id):
                continue
            ids = universe_for_period(str(snapshot.date()), str(snapshot.date()))
            guard(rq, task=f"{task}:{chunk_id}")
            frame = normalize_frame(call_with_retry(rq.get_instrument_industry, ids, source=source, level=1, date=snapshot))
            frame["snapshot_date"] = snapshot
            stage_write(frame, task, chunk_id, year=snapshot.year)
            manifest.mark_chunk_done(task, chunk_id)
        for year in sorted({d.year for d in month_ends}):
            merge_partition(task, year, ("snapshot_date", "order_book_id"))
        manifest.set_status(task, "COMPLETE")

    # 中信衍生产业链/产业/风格板块，按月保存历史快照避免未来函数。
    task = "industry_chain_citics"
    manifest.set_status(task, "RUNNING")
    for snapshot in month_ends:
        chunk_id = snapshot.strftime("%Y-%m")
        if manifest.is_done(task, chunk_id):
            continue
        ids = universe_for_period(str(snapshot.date()), str(snapshot.date()))
        guard(rq, task=f"{task}:{chunk_id}")
        frame = normalize_frame(call_with_retry(
            rq.get_instrument_industry,
            ids,
            source="citics_2019",
            level="citics_sector",
            date=snapshot,
        ))
        frame["snapshot_date"] = snapshot
        stage_write(frame, task, chunk_id, year=snapshot.year)
        manifest.mark_chunk_done(task, chunk_id)
    for year in sorted({d.year for d in month_ends}):
        merge_partition(task, year, ("snapshot_date", "order_book_id"))
    manifest.set_status(task, "COMPLETE")

    for index_id in INDEXES:
        safe_index = index_id.replace(".", "_")
        for kind, api in (("index_components", rq.index_components), ("index_weights", rq.index_weights)):
            task = f"{kind}_{safe_index}"
            manifest.set_status(task, "RUNNING")
            for snapshot in month_ends:
                chunk_id = snapshot.strftime("%Y-%m")
                if manifest.is_done(task, chunk_id):
                    continue
                guard(rq, task=f"{task}:{chunk_id}")
                result = normalize_frame(call_with_retry(api, index_id, date=snapshot))
                result["snapshot_date"] = snapshot
                result["index_id"] = index_id
                stage_write(result, task, chunk_id, year=snapshot.year)
                manifest.mark_chunk_done(task, chunk_id)
            for year in sorted({d.year for d in month_ends}):
                merge_partition(task, year, ("snapshot_date", "order_book_id"))
            manifest.set_status(task, "COMPLETE")

    # 估值和换手率按年/股票批次拉取。
    probe_ids = universe_for_period("2021-03-01", "2021-03-03")
    factors = _probe_factors(rq, probe_ids[0])
    atomic_parquet(pd.DataFrame({"factor": factors}), STD_ROOT / "valuation_factors.parquet")
    for task in ("valuation", "turnover"):
        manifest.set_status(task, "RUNNING")
        for year in range(int(start[:4]), int(end[:4]) + 1):
            ys, ye = max(start, f"{year}-01-01"), min(end, f"{year}-12-31")
            groups = list(chunks(universe_for_period(ys, ye), CHUNK_SIZE))
            for index, group in enumerate(groups):
                chunk_id = f"{year}#{index:03d}"
                if manifest.is_done(task, chunk_id):
                    continue
                guard(rq, task=f"{task}:{chunk_id}")
                if task == "valuation":
                    frame = call_with_retry(rq.get_factor, group, factors, ys, ye) if factors else pd.DataFrame()
                else:
                    frame = normalize_frame(call_with_retry(rq.get_turnover_rate, group, ys, ye))
                    if "year" in frame.columns:
                        frame = frame.rename(columns={"year": "year_rate"})
                stage_write(frame, task, chunk_id, year=year)
                manifest.mark_chunk_done(task, chunk_id)
            merge_partition(task, year, ("date", "order_book_id"))
        manifest.set_status(task, "COMPLETE")
