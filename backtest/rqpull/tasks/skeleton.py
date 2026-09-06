from __future__ import annotations

import pandas as pd

from ..config import END_DATE, MARKET_START, STD_ROOT
from ..io import atomic_parquet, normalize_frame
from ..quota import guard
from ..retry import call_with_retry
from ..state import Manifest


def run(rq, manifest: Manifest) -> None:
    tasks = (
        ("trading_calendar", lambda: pd.DataFrame({"date": rq.get_trading_dates(MARKET_START, END_DATE)})),
        ("instruments", lambda: rq.all_instruments(type="CS")),
        ("index_instruments", lambda: rq.all_instruments(type="INDX")),
        ("yield_curve", lambda: rq.get_yield_curve(MARKET_START, END_DATE)),
    )
    for name, loader in tasks:
        if manifest.task(name)["status"] == "COMPLETE" and (STD_ROOT / f"{name}.parquet").exists():
            continue
        manifest.set_status(name, "RUNNING")
        guard(rq, task=name)
        frame = normalize_frame(call_with_retry(loader))
        if frame.empty:
            manifest.set_status(name, "DIRTY", "接口返回空数据")
            raise RuntimeError(f"{name} 返回空数据")
        atomic_parquet(frame, STD_ROOT / f"{name}.parquet")
        manifest.mark_chunk_done(name, "all")
        manifest.set_status(name, "COMPLETE")

