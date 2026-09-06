from __future__ import annotations

import os
from pathlib import Path

import duckdb

from .config import RAW_ROOT, STD_ROOT
from .io import merge_partition


def uppercase_order_book_ids(tasks=("st_flag", "suspension", "return_calibration")) -> int:
    repaired = 0
    con = duckdb.connect()
    try:
        for root in (RAW_ROOT, STD_ROOT):
            for task in tasks:
                for path in root.joinpath(task).rglob("*.parquet"):
                    if path.name.startswith("._"):
                        continue
                    escaped = str(path).replace("'", "''")
                    columns = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{escaped}')").fetchall()]
                    if "order_book_id" not in columns:
                        continue
                    temp = path.with_name(f".{path.name}.repair")
                    con.execute(
                        f"COPY (SELECT * REPLACE(upper(order_book_id) AS order_book_id) "
                        f"FROM read_parquet('{escaped}')) TO '{str(temp).replace("'", "''")}' "
                        "(FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 3)"
                    )
                    os.replace(temp, path)
                    repaired += 1
    finally:
        con.close()
    return repaired


def rename_turnover_year_rate() -> int:
    """保留 API 滚动年换手率，并与 Hive 分区年份分开。"""
    con = duckdb.connect()
    repaired = 0
    try:
        for path in RAW_ROOT.joinpath("turnover").glob("year=*/part-*.parquet"):
            columns = [r[0] for r in con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{str(path).replace("'", "''")}', hive_partitioning=false)"
            ).fetchall()]
            if "year_rate" in columns or "year" not in columns:
                continue
            temp = path.with_name(f".{path.name}.repair")
            con.execute(
                f"COPY (SELECT * RENAME(year AS year_rate) FROM read_parquet("
                f"'{str(path).replace("'", "''")}', hive_partitioning=false)) "
                f"TO '{str(temp).replace("'", "''")}' (FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 3)"
            )
            os.replace(temp, path)
            repaired += 1
    finally:
        con.close()
    for year_dir in sorted(RAW_ROOT.joinpath("turnover").glob("year=*")):
        merge_partition("turnover", int(year_dir.name.split("=", 1)[1]), ("date", "order_book_id"))
    return repaired
