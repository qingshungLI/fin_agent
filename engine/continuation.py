"""研究续接管线：校验父批次来源，复制只读研究证据，继承待办队列与记忆。

父批次与新批次必须使用同一代码、数据和统计口径。继承结构只用于研究记忆和生成
新假设，不成为新批次的独立重复试验，也不自动获得确认资格。
"""

import json
import re
import shutil
from pathlib import Path
from typing import Any

from engine.audit import write_json
from engine.cache import file_hash
from engine.cycle import initial_tasks


def inherit_research(root: Path, folder: Path, source_id: str,
                     identity: dict[str, Any]) -> dict[str, Any]:
    """复制已核验的父批次证据并返回续接状态。

    Args:
        root: 研究批次公共目录。
        folder: 新批次目录，不得等于父批次目录。
        source_id: 已结束父批次 ID。
        identity: 新批次冻结身份；允许变化的只是预算和调度开关。
    Returns:
        dict[str, Any]: 继承 ID、来源、队列、哈希和后验快照；不改变父批次。
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", source_id):
        raise ValueError("Invalid continuation run ID")
    source = root / source_id
    if source.resolve() == folder.resolve():
        raise ValueError("Continuation must use a new run ID")
    state = json.loads((source / "checkpoint.json").read_text(encoding="utf-8"))
    if state["status"] not in {"COMPLETED", "FAILED"}:
        raise ValueError("Continuation source must be a stopped run")
    if state.get("pending_postprocess"):
        raise ValueError("Resume source postprocessing before continuing into a new run")
    previous = state["identity"]
    for key in ("code", "sources", "data_root", "model", "environment", "discovery", "bayes"):
        if previous.get(key) != identity.get(key):
            raise ValueError(f"Continuation provenance mismatch: {key}")
    mutable = {"max_structures", "auto_evolve", "continue_from", "llm_max_calls", "workers"}
    for key in previous["config"].keys() | identity["config"].keys():
        if key not in mutable and identity["config"].get(key) != previous["config"].get(key):
            raise ValueError(f"Continuation statistical configuration mismatch: {key}")
    for relative, expected in state.get("artifact_hashes", {}).items():
        path = (source / relative).resolve()
        if not path.is_relative_to(source.resolve()) or file_hash(path) != expected:
            raise ValueError(f"Continuation artifact changed: {relative}")
    ids = list(dict.fromkeys(state.get("inherited", []) + state["completed"]))
    hashes, origins = {}, dict(state.get("source_runs", {}))
    for sid in ids:
        if not re.fullmatch(r"S-[A-Za-z0-9-]+", sid):
            raise ValueError("Invalid inherited structure ID")
        src, dst = source / sid, folder / sid
        if not src.is_dir():
            raise ValueError(f"Missing inherited structure: {sid}")
        for required in ("result.json", "daily-ic.parquet", "research-factor.parquet", "frozen.json"):
            relative = str((src / required).relative_to(source))
            if relative not in state.get("artifact_hashes", {}):
                raise ValueError(f"Unverified inherited artifact: {relative}")
        dst.mkdir(exist_ok=True)
        for path in src.iterdir():
            relative = str(path.relative_to(source))
            if not path.is_file() or relative not in state["artifact_hashes"]:
                raise ValueError(f"Unverified inherited file: {relative}")
            target = dst / path.name
            expected = state["artifact_hashes"][relative]
            if target.exists():
                if file_hash(target) != expected:
                    raise ValueError(f"Continuation destination changed: {relative}")
                continue
            # Atomic replacement permits restarting interrupted inheritance.
            temporary = dst / (path.name + ".copying")
            shutil.copy2(path, temporary)
            if file_hash(temporary) != expected:
                raise ValueError(f"Source changed during inheritance: {relative}")
            temporary.replace(target)
        for path in dst.iterdir():
            if path.is_file():
                hashes[str(path.relative_to(folder))] = file_hash(path)
        origins.setdefault(sid, source_id)
    posterior = {"state": "UNIDENTIFIABLE", "terms": []}
    if "memory.json" in state.get("artifact_hashes", {}):
        posterior = json.loads((source / "memory.json").read_text(encoding="utf-8"))
    payload = {"source_run": source_id, "source_checkpoint_hash": file_hash(source / "checkpoint.json"),
               "structures": ids, "source_runs": origins, "posterior": posterior,
               "independent_repetitions": 0}
    write_json(folder / "continuation.json", payload)
    hashes["continuation.json"] = file_hash(folder / "continuation.json")
    queue = state.get("queue", [task.model_dump() for task in initial_tasks()])
    return {"inherited": ids, "source_runs": origins, "queue": queue,
            "queued_keys": state.get("queued_keys", []), "artifact_hashes": hashes,
            "posterior": posterior, "attempts": 0}


def prioritize_queue(queue: list[dict[str, Any]], remaining: int,
                     completed: int) -> None:
    """排序下一次任务，优先异质性进化并保留有限种子探索。

    Args:
        queue: 原地调整的待办列表。
        remaining: 当前批次剩余尝试次数。
        completed: 已完成测量数量，前四次优先冷启动。
    Returns:
        None: 种子和子结构交替；冷启动后优先机制子代，每四次保留一次种子探索。
    """
    seeds = [i for i, task in enumerate(queue) if task["operator"] == "seed"]
    children = [i for i, task in enumerate(queue) if task["operator"] != "seed"]
    if not queue:
        return
    if seeds and (completed < 4 or not children or completed % 4 == 0):
        index = seeds[0]
    elif children:
        index = children[0]
    else:
        index = 0
    queue.insert(0, queue.pop(index))
