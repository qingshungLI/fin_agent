"""性能复核管线：核验已完成结构及面板缓存，重放同一发现阶段并比较原统计结果。

只读取冻结的 A 段数据和既有信号，不重新生成因子或调用模型。输出包含原耗时、
新耗时、实际工作进程和逐折一致性；性能数字是同机历史比较，不是同步配对试验。
"""

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from engine.audit import write_json
from engine.cache import file_hash
from engine.config import ResearchConfig
from engine.data import MarketPanel
from engine.discovery import repeat_splits, variance_vs_mean_screen


def read_json(path: Path) -> dict[str, Any]:
    """从 path 读取 UTF-8 JSON，返回字典；文件不存在或损坏时抛出异常。"""
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    """解析批次、结构和进程参数并重放发现阶段，返回退出码；仅接受已冻结产物。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", required=True)
    parser.add_argument("--structure", required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    folder = ROOT / "artifacts" / args.source_run
    state = read_json(folder / "checkpoint.json")
    if args.structure not in state["completed"]:
        raise ValueError("Benchmark source must be a completed structure")
    destination = folder / args.structure
    for name in ("result.json", "research-factor.parquet", "contribution.parquet"):
        path = destination / name
        if file_hash(path) != state["artifact_hashes"][str(path.relative_to(folder))]:
            raise ValueError(f"Frozen artifact changed: {name}")
    row = read_json(destination / "result.json")
    baseline = row["discovery"]["forest"]
    config = ResearchConfig.model_validate({**state["identity"]["config"], "workers": args.workers})
    cache_matches = []
    for manifest in (ROOT / "artifacts" / "cache").glob("*/manifest.json"):
        meta = read_json(manifest)
        identity = meta["identity"]
        if (identity["data"] == state["identity"]["sources"]
                and all(identity["config"][key] == config.model_dump()[key] for key in identity["config"])
                and all(value == state["identity"]["code"][key] for key, value in identity["code"].items())
                and identity.get("start") is None and identity.get("end") is None):
            cache_matches.append((manifest.parent, meta))
    if len(cache_matches) != 1:
        raise ValueError(f"Expected one matching frozen panel cache, found {len(cache_matches)}")
    cache, meta = cache_matches[0]
    candidates = row["discovery"]["screen"]["exploratory_candidates"]
    screen_names = [item["name"] for item in row["discovery"]["screen"]["rows"]]
    names = set(screen_names + candidates + ["market_cap", "realized_vol", "turnover_today", "industry"])
    horizon = row["structure"]["primary_horizon"]
    label = f"industry_resid_{horizon}"
    data = {}
    for name in [f"fields-{name}" for name in sorted(names)] + [f"labels-{label}"]:
        path = cache / f"{name}.parquet"
        if file_hash(path) != meta["files"][path.name]:
            raise ValueError(f"Cache changed: {name}")
        data[name] = pd.read_parquet(path)
    panel = MarketPanel({name: data[f"fields-{name}"] for name in names},
                        {label: data[f"labels-{label}"]}, meta["report"])
    signal = pd.read_parquet(destination / "research-factor.parquet")
    contribution = pd.read_parquet(destination / "contribution.parquet")
    cuts = read_json(folder / "cuts.json")
    print(f"benchmark loaded frozen signal {signal.shape}; workers={config.workers}", flush=True)
    with threadpool_limits(limits=1):
        started = perf_counter()
        screened = variance_vs_mean_screen(contribution, panel.fields, screen_names, config)
        selected = [item["name"] for item in sorted(screened["rows"], key=lambda item: (item["mean_p"], item["name"]))[:2]]
        if selected != candidates:
            raise AssertionError("Screen candidate ordering changed")
        measured = repeat_splits(panel, signal, selected, cuts, config, horizon)
        elapsed = perf_counter() - started
    matches = (np.allclose(measured["fold_p"], baseline["fold_p"], rtol=1e-8, atol=1e-10)
               and measured["selection_frequency"] == baseline["selection_frequency"])
    result = {"source_run": args.source_run, "structure": args.structure,
              "baseline_seconds": row["timings"]["discovery_seconds"], "elapsed_seconds": elapsed,
              "speedup": row["timings"]["discovery_seconds"] / elapsed,
              "statistical_match": bool(matches), "baseline": baseline, "measured": measured,
              "code": {p.name: file_hash(p) for p in (ROOT / "engine").glob("*.py")}}
    write_json(args.output, result)
    print(json.dumps({key: result[key] for key in ("elapsed_seconds", "speedup", "statistical_match")}), flush=True)
    return 0 if matches else 2


if __name__ == "__main__":
    raise SystemExit(main())