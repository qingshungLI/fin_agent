from __future__ import annotations

from datetime import date

from ..config import CHUNK_SIZE, END_DATE, MARKET_START
from ..io import merge_partition, stage_write
from ..quota import guard
from ..retry import call_with_retry
from ..state import Manifest
from .common import chunks, universe_for_period


def run(rq, manifest: Manifest, start: str = MARKET_START, end: str = END_DATE) -> None:
    task = "daily_bar"
    manifest.set_status(task, "RUNNING")
    for year in range(int(start[:4]), int(end[:4]) + 1):
        year_start = max(start, f"{year}-01-01")
        year_end = min(end, f"{year}-12-31")
        ids = universe_for_period(year_start, year_end)
        groups = list(chunks(ids, CHUNK_SIZE))
        for index, group in enumerate(groups):
            chunk_id = f"{year}#{index:03d}"
            if manifest.is_done(task, chunk_id):
                continue
            guard(rq, task=f"{task}:{chunk_id}")
            frame = call_with_retry(
                rq.get_price,
                group,
                year_start,
                year_end,
                frequency="1d",
                adjust_type="none",
                skip_suspended=False,
                expect_df=True,
            )
            stage_write(frame, task, chunk_id, year=year)
            manifest.mark_chunk_done(task, chunk_id)
        if all(manifest.is_done(task, f"{year}#{i:03d}") for i in range(len(groups))):
            merge_partition(task, year, ("date", "order_book_id"))
    manifest.set_status(task, "COMPLETE")

