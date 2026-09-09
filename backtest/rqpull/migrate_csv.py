"""历史迁移管线：合并旧 CSV、按年写入去重 Parquet，行数核对成功后才移除源 CSV。迁移不是研究入口，调用前应确认目标数据目录。"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

from .config import ARCHIVE_ROOT, PROJECT_ROOT


def _valid_csv_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.glob("*.csv") if not p.name.startswith("._"))


def migrate_and_delete() -> dict:
    """迁移配置目录中的两套旧 CSV，无参数，核对行数后才删除源文件。

    Returns:
        dict: 迁移状态、输入行数、唯一行数和已删除文件数。
    """
    sources = [PROJECT_ROOT / "cache" / "per_stock_csv", PROJECT_ROOT / "cache" / "per_stock_csv_rebuild"]
    files = [p for source in sources for p in _valid_csv_files(source)]
    if not files:
        return {"status": "NO_CSV", "files_deleted": 0}
    out_dir = ARCHIVE_ROOT / "legacy_adjusted"
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        file_sql = "[" + ",".join("'" + str(p).replace("'", "''") + "'" for p in files) + "]"
        con.execute(
            f"""CREATE OR REPLACE TEMP TABLE legacy AS
            SELECT *,
              CASE
                WHEN regexp_extract(filename, '([^/]+)\\.csv$', 1) LIKE 'SH%'
                  THEN substr(regexp_extract(filename, '([^/]+)\\.csv$', 1), 3) || '.XSHG'
                WHEN regexp_extract(filename, '([^/]+)\\.csv$', 1) LIKE 'SZ%'
                  THEN substr(regexp_extract(filename, '([^/]+)\\.csv$', 1), 3) || '.XSHE'
              END AS order_book_id,
              CASE WHEN filename LIKE '%per_stock_csv_rebuild/%' THEN 2 ELSE 1 END AS source_priority
            FROM read_csv_auto({file_sql}, filename=true, union_by_name=true, header=true)"""
        )
        source_rows = con.execute("SELECT count(*) FROM legacy").fetchone()[0]
        unique_rows = con.execute("SELECT count(*) FROM (SELECT DISTINCT date, order_book_id FROM legacy)").fetchone()[0]
        years = [r[0] for r in con.execute("SELECT DISTINCT year(CAST(date AS DATE)) FROM legacy ORDER BY 1").fetchall()]
        written = []
        for year in years:
            directory = out_dir / f"year={year}"
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / "data.parquet"
            temp = directory / ".data.parquet.tmp"
            temp_sql = str(temp).replace("'", "''")
            con.execute(
                f"""COPY (
                    SELECT * EXCLUDE(filename, source_priority)
                    FROM legacy
                    WHERE year(CAST(date AS DATE))={int(year)}
                    QUALIFY row_number() OVER (
                      PARTITION BY CAST(date AS DATE), order_book_id ORDER BY source_priority DESC
                    )=1
                    ORDER BY CAST(date AS DATE), order_book_id
                ) TO '{temp_sql}'
                (FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 3)"""
            )
            os.replace(temp, target)
            written.append(target)
        parquet_rows = 0
        for path in written:
            path_sql = str(path).replace("'", "''")
            parquet_rows += con.execute(
                f"SELECT count(*) FROM read_parquet('{path_sql}')"
            ).fetchone()[0]
        if parquet_rows != unique_rows or parquet_rows <= 0:
            raise RuntimeError(f"CSV 迁移校验失败：唯一行 {unique_rows}，Parquet 行 {parquet_rows}")
    finally:
        con.close()

    deleted = 0
    for source in sources:
        for path in source.iterdir() if source.exists() else ():
            if path.is_file() and (path.suffix == ".csv" or path.name.startswith("._")):
                path.unlink()
                deleted += 1
        try:
            source.rmdir()
        except OSError:
            pass
    return {
        "status": "MIGRATED",
        "source_rows": source_rows,
        "unique_rows": unique_rows,
        "parquet_rows": parquet_rows,
        "files_deleted": deleted,
        "partitions": len(written),
    }
