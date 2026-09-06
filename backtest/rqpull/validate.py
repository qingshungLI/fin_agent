from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from .config import STATE_ROOT, STD_ROOT
from .state import Manifest


def validate_daily_bar(manifest: Manifest | None = None) -> dict:
    manifest = manifest or Manifest()
    files = sorted((STD_ROOT / "daily_bar").glob("year=*/data.parquet"))
    report = {"task": "daily_bar", "checked_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(), "partitions": []}
    if not files:
        report["status"] = "MISSING"
        return report
    overall = "CLEAN"
    con = duckdb.connect()
    try:
        for path in files:
            escaped = str(path).replace("'", "''")
            row = con.execute(
                f"""SELECT
                    count(*) AS rows,
                    count(*) - count(DISTINCT (date, order_book_id)) AS duplicates,
                    count(*) FILTER (WHERE close <= 0) AS bad_close,
                    count(*) FILTER (WHERE high < low OR close > high OR close < low) AS bad_ohlc,
                    count(*) FILTER (WHERE volume < 0 OR total_turnover < 0) AS bad_flow,
                    min(date), max(date), count(DISTINCT order_book_id)
                FROM read_parquet('{escaped}')"""
            ).fetchone()
            item = {
                "path": str(path), "rows": row[0], "duplicates": row[1], "bad_close": row[2],
                "bad_ohlc": row[3], "bad_flow": row[4], "min_date": str(row[5]),
                "max_date": str(row[6]), "instruments": row[7],
            }
            item["status"] = "CLEAN" if not any(item[k] for k in ("duplicates", "bad_close", "bad_ohlc", "bad_flow")) else "DIRTY"
            if item["status"] == "DIRTY":
                overall = "DIRTY"
                manifest.mark_dirty("daily_bar", str(path), json.dumps(item, ensure_ascii=False))
            report["partitions"].append(item)
    finally:
        con.close()
    report["status"] = overall
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    (STATE_ROOT / "validation_daily_bar.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def validate_open_auction(manifest: Manifest | None = None) -> dict:
    manifest = manifest or Manifest()
    files = sorted((STD_ROOT / "open_auction").glob("year=*/data.parquet"))
    report = {
        "task": "open_auction",
        "checked_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "partitions": [],
    }
    if not files:
        report["status"] = "MISSING"
        return report
    overall = "CLEAN"
    con = duckdb.connect()
    try:
        for path in files:
            escaped = str(path).replace("'", "''")
            row = con.execute(
                f"""SELECT
                    count(*) AS rows,
                    count(*) - count(DISTINCT (datetime, order_book_id)) AS duplicates,
                    count(*) FILTER (WHERE datetime IS NULL OR order_book_id IS NULL) AS bad_key,
                    count(*) FILTER (WHERE volume < 0 OR total_turnover < 0) AS bad_flow,
                    count(*) FILTER (WHERE limit_up IS NULL OR limit_down IS NULL) AS missing_limits,
                    count(*) FILTER (WHERE last = 0) AS zero_last,
                    min(datetime), max(datetime), count(DISTINCT order_book_id)
                FROM read_parquet('{escaped}')"""
            ).fetchone()
            item = {
                "path": str(path), "rows": row[0], "duplicates": row[1],
                "bad_key": row[2], "bad_flow": row[3], "missing_limits": row[4],
                "zero_last": row[5], "min_datetime": str(row[6]),
                "max_datetime": str(row[7]), "instruments": row[8],
            }
            bad_fields = ("duplicates", "bad_key", "bad_flow", "missing_limits")
            item["status"] = "CLEAN" if not any(item[key] for key in bad_fields) else "DIRTY"
            if item["status"] == "DIRTY":
                overall = "DIRTY"
                manifest.mark_dirty("open_auction", str(path), json.dumps(item, ensure_ascii=False))
            report["partitions"].append(item)
    finally:
        con.close()
    report["rows"] = sum(item["rows"] for item in report["partitions"])
    report["zero_last"] = sum(item["zero_last"] for item in report["partitions"])
    report["status"] = overall
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    (STATE_ROOT / "validation_open_auction.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def validate_industry_chain_citics(manifest: Manifest | None = None) -> dict:
    manifest = manifest or Manifest()
    files = sorted((STD_ROOT / "industry_chain_citics").glob("year=*/data.parquet"))
    report = {
        "task": "industry_chain_citics",
        "checked_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "partitions": [],
    }
    if not files:
        report["status"] = "MISSING"
        return report
    overall = "CLEAN"
    con = duckdb.connect()
    try:
        for path in files:
            escaped = str(path).replace("'", "''")
            row = con.execute(
                f"""SELECT
                    count(*) AS rows,
                    count(*) - count(DISTINCT (snapshot_date, order_book_id)) AS duplicates,
                    count(*) FILTER (WHERE snapshot_date IS NULL OR order_book_id IS NULL) AS bad_key,
                    count(*) FILTER (
                        WHERE coalesce(industry_sector_name, '') = ''
                          AND coalesce(industry_chain_sector_name, '') = ''
                          AND coalesce(style_sector_name, '') = ''
                    ) AS missing_all_sector,
                    count(*) FILTER (WHERE coalesce(industry_sector_name, '') = '') AS missing_industry_sector,
                    count(*) FILTER (WHERE coalesce(industry_chain_sector_name, '') = '') AS missing_industry_chain_sector,
                    count(*) FILTER (WHERE coalesce(style_sector_name, '') = '') AS missing_style_sector,
                    min(snapshot_date), max(snapshot_date), count(DISTINCT order_book_id)
                FROM read_parquet('{escaped}')"""
            ).fetchone()
            item = {
                "path": str(path),
                "rows": row[0],
                "duplicates": row[1],
                "bad_key": row[2],
                "missing_all_sector": row[3],
                "missing_industry_sector": row[4],
                "missing_industry_chain_sector": row[5],
                "missing_style_sector": row[6],
                "min_snapshot_date": str(row[7]),
                "max_snapshot_date": str(row[8]),
                "instruments": row[9],
            }
            bad_fields = ("duplicates", "bad_key")
            item["status"] = "CLEAN" if not any(item[key] for key in bad_fields) else "DIRTY"
            if item["status"] == "DIRTY":
                overall = "DIRTY"
                manifest.mark_dirty("industry_chain_citics", str(path), json.dumps(item, ensure_ascii=False))
            report["partitions"].append(item)
    finally:
        con.close()
    report["rows"] = sum(item["rows"] for item in report["partitions"])
    report["missing_all_sector"] = sum(item["missing_all_sector"] for item in report["partitions"])
    report["missing_industry_sector"] = sum(item["missing_industry_sector"] for item in report["partitions"])
    report["missing_industry_chain_sector"] = sum(item["missing_industry_chain_sector"] for item in report["partitions"])
    report["missing_style_sector"] = sum(item["missing_style_sector"] for item in report["partitions"])
    report["status"] = overall
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    (STATE_ROOT / "validation_industry_chain_citics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def validate_task(task: str) -> dict:
    if task == "daily_bar":
        return validate_daily_bar()
    if task == "open_auction":
        return validate_open_auction()
    if task == "industry_chain_citics":
        return validate_industry_chain_citics()
    files = sorted((STD_ROOT / task).rglob("*.parquet"))
    return {"task": task, "status": "CLEAN" if files else "MISSING", "files": len(files)}
