from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from zoneinfo import ZoneInfo

import pandas as pd

from .config import (
    PARQUET_COMPRESSION,
    PARQUET_COMPRESSION_LEVEL,
    RAW_ROOT,
    STATE_ROOT,
    STD_ROOT,
    ensure_directories,
)


def normalize_frame(frame) -> pd.DataFrame:
    if frame is None:
        return pd.DataFrame()
    if isinstance(frame, (list, tuple)) and (not frame or isinstance(frame[0], str)):
        frame = pd.DataFrame({"order_book_id": list(frame)})
    elif isinstance(frame, dict):
        try:
            frame = pd.DataFrame(frame)
        except ValueError:
            frame = pd.DataFrame([frame])
    elif not isinstance(frame, (pd.DataFrame, pd.Series)):
        frame = pd.DataFrame(frame)
    if isinstance(frame, pd.Series):
        frame = frame.to_frame()
    frame = frame.copy()
    if not isinstance(frame.index, pd.RangeIndex) or frame.index.name:
        frame = frame.reset_index()
    def normalize_column(column) -> str:
        text = str(column).strip()
        if re.fullmatch(r"\d{6}\.(xshe|xshg)", text, flags=re.IGNORECASE):
            return text.upper()
        return text.lower().replace(" ", "_")

    frame.columns = [normalize_column(c) for c in frame.columns]
    for candidate in ("tradedate", "trading_date"):
        if candidate in frame.columns and "date" not in frame.columns:
            frame = frame.rename(columns={candidate: "date"})
    for column in frame.columns:
        if column == "date" or column.endswith("_date") or column in ("datetime", "original_time"):
            try:
                frame[column] = pd.to_datetime(frame[column], errors="coerce")
            except (TypeError, ValueError):
                pass
    return frame


def atomic_parquet(frame: pd.DataFrame, path: Path) -> Path:
    ensure_directories()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    frame.to_parquet(
        temp,
        index=False,
        compression=PARQUET_COMPRESSION,
        compression_level=PARQUET_COMPRESSION_LEVEL,
    )
    os.replace(temp, path)
    return path


def stage_write(frame, task: str, chunk_id: str, year: int | None = None, month: int | None = None) -> Path | None:
    normalized = normalize_frame(frame)
    if normalized.empty:
        return None
    directory = RAW_ROOT / task
    if year is not None:
        directory /= f"year={year:04d}"
    if month is not None:
        directory /= f"month={month:02d}"
    return atomic_parquet(normalized, directory / f"part-{chunk_id}.parquet")


def merge_partition(task: str, year: int, primary_key: tuple[str, ...], month: int | None = None) -> Path | None:
    import duckdb

    raw_dir = RAW_ROOT / task / f"year={year:04d}"
    std_dir = STD_ROOT / task / f"year={year:04d}"
    if month is not None:
        raw_dir /= f"month={month:02d}"
        std_dir /= f"month={month:02d}"
    files = sorted(raw_dir.glob("part-*.parquet"))
    if not files:
        return None
    std_dir.mkdir(parents=True, exist_ok=True)
    output = std_dir / "data.parquet"
    temp = std_dir / ".data.parquet.tmp"
    file_sql = "[" + ",".join("'" + str(p).replace("'", "''") + "'" for p in files) + "]"
    keys = ", ".join(f'"{key}"' for key in primary_key)
    con = duckdb.connect()
    try:
        con.execute(
            f"COPY (SELECT * FROM read_parquet({file_sql}, union_by_name=true) "
            f"QUALIFY row_number() OVER (PARTITION BY {keys} ORDER BY {keys}) = 1 "
            f"ORDER BY {keys}) TO '{str(temp).replace("'", "''")}' "
            f"(FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 3)"
        )
    finally:
        con.close()
    os.replace(temp, output)
    write_partition_metadata(task, output, primary_key)
    return output


def write_partition_metadata(task: str, path: Path, primary_key: tuple[str, ...]) -> None:
    import pyarrow.parquet as pq

    metadata = pq.ParquetFile(path).metadata
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    record = {
        "task": task,
        "path": str(path),
        "rows": metadata.num_rows,
        "columns": metadata.schema.names,
        "primary_key": list(primary_key),
        "bytes": path.stat().st_size,
        "sha256": checksum,
        "written_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
    }
    out = STATE_ROOT / "partitions" / (path.relative_to(STD_ROOT).as_posix().replace("/", "__") + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=out.parent, delete=False) as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
        temp = Path(fh.name)
    os.replace(temp, out)
