from __future__ import annotations

import pandas as pd

from ..config import END_DATE, MIN_FREE_NEWS, NEWS_CHUNK_SIZE, NEWS_START, ARCHIVE_ROOT
from ..io import atomic_parquet, normalize_frame, stage_write
from ..quota import guard
from ..retry import call_with_retry
from ..state import Manifest
from .common import chunks, universe_for_period


TEXT_FIELDS = ("news_id", "title", "url", "source")


def _months(start: str, end: str):
    for period in pd.period_range(start[:7], end[:7], freq="M"):
        month_start = max(start, str(period.start_time.date()))
        month_end = min(end, str(period.end_time.date()))
        yield period, month_start, month_end


def run(rq, manifest: Manifest, start: str = NEWS_START, end: str = END_DATE) -> None:
    if not hasattr(rq, "news") or not hasattr(rq.news, "get_stock_news"):
        raise PermissionError("rqdatac_news 未安装或 news 插件未注册")
    task = "news"
    manifest.set_status(task, "RUNNING")
    for period, month_start, month_end in _months(start, end):
        ids = universe_for_period(month_start, month_end)
        groups = list(chunks(ids, NEWS_CHUNK_SIZE))
        for index, group in enumerate(groups):
            chunk_id = f"{period}#{index:03d}"
            if manifest.is_done(task, chunk_id):
                continue
            guard(rq, min_free=MIN_FREE_NEWS, task=f"{task}:{chunk_id}")
            frame = normalize_frame(call_with_retry(rq.news.get_stock_news, group, month_start, month_end))
            if not frame.empty:
                text_columns = [c for c in TEXT_FIELDS if c in frame.columns]
                meta = frame.drop(columns=[c for c in ("title", "url") if c in frame.columns])
                stage_write(meta, "news_meta", chunk_id, year=period.year, month=period.month)
                if text_columns:
                    text = frame[text_columns].drop_duplicates(subset=["news_id"] if "news_id" in text_columns else None)
                    path = ARCHIVE_ROOT / "news_text" / f"year={period.year:04d}" / f"month={period.month:02d}" / f"part-{chunk_id}.parquet"
                    atomic_parquet(text, path)
            manifest.mark_chunk_done(task, chunk_id)
    manifest.set_status(task, "COMPLETE")

