from __future__ import annotations

from datetime import date
from pathlib import Path

# 回测迁移后，数据由宿主项目统一管理；环境变量用于测试时切换数据集。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(
    __import__("os").environ.get("FINANCE_DATA_ROOT", str(PROJECT_ROOT / "data"))
).expanduser()
RAW_ROOT = DATA_ROOT / "raw"
# finance_agent 的现有数据已经是标准化 Parquet，直接把数据根作为视图扫描根。
STD_ROOT = DATA_ROOT
ARCHIVE_ROOT = DATA_ROOT / "archive"
STATE_ROOT = DATA_ROOT / "_state"
MANIFEST_PATH = STATE_ROOT / "manifest.json"
QUOTA_LOG_PATH = STATE_ROOT / "quota_log.jsonl"
WAREHOUSE_PATH = DATA_ROOT / "warehouse.duckdb"

MARKET_START = "2016-07-01"
NEWS_START = "2017-01-01"
END_DATE = "2026-07-30"
WARMUP = ("2016-07-01", "2016-12-31")
IN_SAMPLE = ("2017-01-01", "2023-12-31")
OOS = ("2024-01-01", END_DATE)
OOS_LOCKED = True

CHUNK_SIZE = 300
NEWS_CHUNK_SIZE = 200
MIN_FREE_DEFAULT = 500 * 1024 * 1024
MIN_FREE_NEWS = 800 * 1024 * 1024
PARQUET_COMPRESSION = "zstd"
PARQUET_COMPRESSION_LEVEL = 3

INDEXES = (
    "000300.XSHG",
    "000905.XSHG",
    "000852.XSHG",
    "000985.XSHG",
)

VALUATION_FACTORS = (
    "market_cap",
    "market_cap_2",
    "a_share_market_val",
    "pe_ratio_ttm",
    "pb_ratio_lf",
    "ps_ratio_ttm",
    "pcf_ratio_ttm",
    "ev",
    "book_to_market_ratio",
)


def ensure_directories() -> None:
    for path in (RAW_ROOT, STD_ROOT, ARCHIVE_ROOT, STATE_ROOT):
        path.mkdir(parents=True, exist_ok=True)


def assert_parameter_search_allowed(start: str | date, end: str | date) -> None:
    """禁止在锁定的样本外区间做参数搜索。"""
    if not OOS_LOCKED:
        return
    start_s, end_s = str(start)[:10], str(end)[:10]
    if start_s <= OOS[1] and end_s >= OOS[0]:
        raise ValueError(f"样本外区间 {OOS[0]}~{OOS[1]} 已锁定，禁止参数搜索")
