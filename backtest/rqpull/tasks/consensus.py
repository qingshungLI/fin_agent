from __future__ import annotations

from ..config import CHUNK_SIZE, END_DATE, MARKET_START
from ..io import merge_partition, stage_write
from ..quota import guard
from ..retry import call_with_retry
from ..state import Manifest
from .common import chunks, universe_for_period


def run(rq, manifest: Manifest, start: str = MARKET_START, end: str = END_DATE) -> None:
    ids = universe_for_period(start, end)
    jobs = (
        ("consensus_security_change", lambda group: rq.consensus.get_security_change(group, start, end)),
        ("consensus_appr_exceed", lambda group: rq.consensus.get_expect_appr_exceed(group, start, end)),
        ("consensus_expect_prob", lambda group: rq.consensus.get_expect_prob(group, None, start, end)),
        ("consensus_analyst_momentum", lambda group: rq.consensus.get_analyst_momentum(group, start_date=start, end_date=end, report_range=3)),
        ("consensus_comp_indicators", lambda group: rq.consensus.get_comp_indicators(group, start, end, report_range=3)),
    )
    for task, loader in jobs:
        manifest.set_status(task, "RUNNING")
        for index, group in enumerate(chunks(ids, CHUNK_SIZE)):
            chunk_id = f"all#{index:03d}"
            if manifest.is_done(task, chunk_id):
                continue
            guard(rq, task=f"{task}:{chunk_id}")
            frame = call_with_retry(loader, group)
            stage_write(frame, task, chunk_id, year=int(end[:4]))
            manifest.mark_chunk_done(task, chunk_id)
        manifest.set_status(task, "COMPLETE")

