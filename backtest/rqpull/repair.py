"""存量修复管线：统一证券代码大小写、区分换手率年份字段与分区年份，然后重建对应分区。只处理配置目录下的已存 Parquet。"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

from .config import RAW_ROOT, STD_ROOT
from .io import merge_partition


def uppercase_order_book_ids(tasks: tuple[str, ...] = ("st_flag", "suspension", "return_calibration")) -> int:
    """统一指定任务的证券代码大小写，假设任务目录由操作者确认。

    Args:
        tasks: 暂存与标准数据根目录下的任务名称。
    Returns:
        int: 成功替换的 Parquet 文件数。
    """
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
                    temp_sql = str(temp).replace("'", "''")
                    con.execute(
                        f"COPY (SELECT * REPLACE(upper(order_book_id) AS order_book_id) "
                        f"FROM read_parquet('{escaped}')) TO '{temp_sql}' "
                        "(FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 3)"
                    )
                    os.replace(temp, path)
                    repaired += 1
    finally:
        con.close()
    return repaired


def rename_turnover_year_rate() -> int:
    """重命名滚动年换手率并重建分区，无参数，假设原 year 字段表示换手率。

    Returns:
        int: 改写的暂存文件数；已有 year_rate 的文件保持不变。
    """
    con = duckdb.connect()
    repaired = 0
    try:
        for path in RAW_ROOT.joinpath("turnover").glob("year=*/part-*.parquet"):
            path_sql = str(path).replace("'", "''")
            columns = [r[0] for r in con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{path_sql}', hive_partitioning=false)"
            ).fetchall()]
            if "year_rate" in columns or "year" not in columns:
                continue
            temp = path.with_name(f".{path.name}.repair")
            temp_sql = str(temp).replace("'", "''")
            con.execute(
                f"COPY (SELECT * RENAME(year AS year_rate) FROM read_parquet("
                f"'{path_sql}', hive_partitioning=false)) "
                f"TO '{temp_sql}' (FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 3)"
            )
            os.replace(temp, path)
            repaired += 1
    finally:
        con.close()
    for year_dir in sorted(RAW_ROOT.joinpath("turnover").glob("year=*")):
        merge_partition("turnover", int(year_dir.name.split("=", 1)[1]), ("date", "order_book_id"))
    return repaired
