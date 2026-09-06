from __future__ import annotations

import json
import random
from datetime import datetime
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from ..config import END_DATE, MARKET_START, STATE_ROOT, STD_ROOT, WAREHOUSE_PATH
from ..io import merge_partition, normalize_frame, stage_write
from ..quota import guard
from ..retry import call_with_retry
from ..state import Manifest
from ..warehouse import build_views
from .common import chunks, load_instruments


def _sample_ids() -> list[str]:
    build_views()
    con = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
    try:
        hs300 = [r[0] for r in con.execute(
            """SELECT DISTINCT order_book_id FROM v_index_components_000300_XSHG
            WHERE snapshot_date=(SELECT max(snapshot_date) FROM v_index_components_000300_XSHG)
            ORDER BY order_book_id"""
        ).fetchall()]
    finally:
        con.close()
    all_ids = sorted(set(load_instruments()["order_book_id"].dropna().astype(str)) - set(hs300))
    rng = random.Random(20260730)
    small_sample = rng.sample(all_ids, min(200, len(all_ids)))
    return sorted(set(hs300 + small_sample))


def run(rq, manifest: Manifest, start: str = MARKET_START, end: str = END_DATE) -> dict:
    task = "return_calibration"
    ids = _sample_ids()
    manifest.set_status(task, "RUNNING")
    for year in range(int(start[:4]), int(end[:4]) + 1):
        ys, ye = max(start, f"{year}-01-01"), min(end, f"{year}-12-31")
        groups = list(chunks(ids, 100))
        for index, group in enumerate(groups):
            chunk_id = f"{year}#{index:03d}"
            if manifest.is_done(task, chunk_id):
                continue
            guard(rq, task=f"{task}:{chunk_id}")
            wide = call_with_retry(rq.get_price_change_rate, group, ys, ye)
            frame = normalize_frame(wide)
            if not frame.empty:
                frame = frame.melt(
                    id_vars=["date"],
                    value_vars=[c for c in frame.columns if c != "date"],
                    var_name="order_book_id",
                    value_name="official_return",
                )
            stage_write(frame, task, chunk_id, year=year)
            manifest.mark_chunk_done(task, chunk_id)
        merge_partition(task, year, ("date", "order_book_id"))
    manifest.set_status(task, "COMPLETE")
    build_views()
    report = validate()
    if not report["passed"]:
        manifest.mark_dirty(task, "all", json.dumps(report, ensure_ascii=False))
        raise RuntimeError("复权收益率校准未达到 99.9% 的 1e-6 误差阈值")
    manifest.task(task)["dirty_partitions"] = []
    manifest.set_status(task, "COMPLETE")
    return report


def validate() -> dict:
    con = duckdb.connect(str(WAREHOUSE_PATH), read_only=True)
    try:
        row = con.execute(
            """WITH sample AS (
                SELECT DISTINCT order_book_id FROM v_return_calibration
            ), bars AS (
                SELECT b.date, b.order_book_id, b.close,
                    lag(b.close) OVER (PARTITION BY b.order_book_id ORDER BY b.date) AS prev_close
                FROM v_daily_bar b JOIN sample s USING(order_book_id)
            ), compared AS (
                SELECT o.date, o.order_book_id, o.official_return,
                    b.close / b.prev_close * coalesce(a.ex_factor, 1.0) - 1.0 AS self_return
                FROM v_return_calibration o
                JOIN bars b USING(date, order_book_id)
                LEFT JOIN v_adj_factor a
                  ON a.order_book_id=o.order_book_id AND a.ex_date=o.date
                WHERE o.official_return IS NOT NULL AND b.prev_close IS NOT NULL
            )
            SELECT count(*),
                avg((abs(official_return-self_return) < 1e-6)::INTEGER)::DOUBLE,
                max(abs(official_return-self_return)),
                quantile_cont(abs(official_return-self_return), 0.999)
            FROM compared"""
        ).fetchone()
    finally:
        con.close()
    report = {
        "checked_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "samples": row[0],
        "within_1e_6_ratio": row[1],
        "max_abs_error": row[2],
        "p999_abs_error": row[3],
        "passed": bool(row[0] and row[1] >= 0.999),
    }
    path = STATE_ROOT / "validation_return_calibration.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
