import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from engine.initial_search import partition_cells,coordinator_lease
from engine.cycle import initial_tasks
from engine.config import ResearchConfig
from engine.pipeline import project_lock
from engine.llm import shared_request_slot


def test_initial_grid_partition_has_complete_disjoint_coverage():
    cells=[f"{t.family}-F{t.form}" for t in initial_tasks()]
    groups=partition_cells(cells,20)
    flattened=[c for group in groups for c in group]
    assert len(groups)==20 and len(flattened)==70
    assert len(set(flattened))==70 and set(flattened)==set(cells)
    for group in groups:
        assert [f"{t.family}-F{t.form}" for t in initial_tasks(group)]==list(group)
    with pytest.raises(ValueError):
        initial_tasks(("M999-F1",))


def test_partitioned_search_cannot_claim_formal_or_adaptive_mode():
    values=dict(mode="fast",provider="llm",auto_evolve=False,max_structures=1,initial_cells=("M2-F3",))
    assert ResearchConfig(**values).initial_cells==("M2-F3",)
    for changes in [dict(mode="formal"),dict(auto_evolve=True),dict(max_structures=2)]:
        with pytest.raises(ValueError):
            ResearchConfig(**{**values,**changes})


@pytest.mark.skipif(os.name!="posix",reason="POSIX coordinator lease")
def test_project_lock_survives_controller_descriptor_close(tmp_path):
    with coordinator_lease(tmp_path) as handle:
        worker_lease=os.dup(handle.fileno())
    try:
        with pytest.raises(RuntimeError,match="writer"):
            with project_lock(tmp_path):pass
    finally:
        os.close(worker_lease)
    with project_lock(tmp_path):pass


@pytest.mark.skipif(os.name!="posix",reason="POSIX request slots")
def test_shared_llm_slots_bound_simultaneous_requests(tmp_path,monkeypatch):
    monkeypatch.setenv("AURORA_LLM_CONCURRENCY","2")
    counts={"active":0,"peak":0};lock=threading.Lock()
    def request(i):
        with shared_request_slot(tmp_path):
            with lock:
                counts["active"]+=1
                counts["peak"]=max(counts["peak"],counts["active"])
            time.sleep(.03)
            with lock:counts["active"]-=1
    with ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(request,range(12)))
    assert counts["peak"]==2 and counts["active"]==0

def test_parent_and_spawned_worker_cache_configuration_match():
    import json
    from engine.initial_search import normalized_config
    parent=normalized_config(ResearchConfig(mode="fast",provider="llm",auto_evolve=False))
    worker=ResearchConfig.model_validate(parent.model_dump())
    assert json.dumps(parent.model_dump(),sort_keys=True)==json.dumps(worker.model_dump(),sort_keys=True)
