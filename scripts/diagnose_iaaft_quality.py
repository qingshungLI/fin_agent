"""IAAFT 质量诊断：复现当前批次的真实掩码和首个替代样本，定位频谱误差的长度组。

只读 A 段缓存和冻结因子。额外迭代只用于工程诊断，不改写原检验、不生成新的 p 值，
不依据误差丢弃证券或放宽原 0.1 质量阈值。
"""
import json
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from engine.audit import write_json
from engine.cache import file_hash
from engine.placebo import spell_plan

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """诊断当前首个结构；无参数，写入独立报告，假设冻结缓存仍完整可验证。"""
    folder = ROOT / "artifacts/fullcycle-20260908"
    state = json.loads((folder / "checkpoint.json").read_text(encoding="utf-8"))
    sid = state["completed"][0]
    row = json.loads((folder / sid / "result.json").read_text(encoding="utf-8"))
    candidates = []
    for path in (ROOT / "artifacts/cache").glob("*/manifest.json"):
        meta = json.loads(path.read_text(encoding="utf-8"))
        identity = meta["identity"]
        if (all(state["identity"]["config"].get(k) == v for k, v in identity["config"].items())
                and all(state["identity"]["code"].get(k) == v for k, v in identity["code"].items())
                and identity["data"] == state["identity"]["sources"]):
            candidates.append((path.parent, meta))
    if len(candidates) != 1:
        raise ValueError(f"Expected one frozen cache, found {len(candidates)}")
    cache, meta = candidates[0]
    horizon = row["structure"]["primary_horizon"]
    name = f"labels-industry_resid_{horizon}.parquet"
    if file_hash(cache / name) != meta["files"][name]:
        raise ValueError("Frozen label cache changed")
    signal = pd.read_parquet(folder / sid / "research-factor.parquet")
    xframe = signal.iloc[len(signal)//2:].iloc[:-11]
    returns = pd.read_parquet(cache / name).reindex_like(xframe)
    x = xframe.where(np.isfinite(returns)).to_numpy(dtype=float)
    plan = spell_plan(x)
    rng = np.random.default_rng(np.random.SeedSequence([state["identity"]["config"]["seed"], 2, 0]))
    started = perf_counter()
    groups = []
    for spell in plan:
        length, columns = spell.values.shape
        if length < 4:
            continue
        order = np.argsort(rng.random(spell.values.shape), axis=0)
        surrogate = np.take_along_axis(spell.values, order, axis=0)
        error = {}
        changed_fraction = None
        for iteration in range(1, 301):
            phase = np.angle(np.fft.rfft(surrogate, axis=0))
            filtered = np.fft.irfft(spell.amplitude*np.exp(1j*phase), n=length, axis=0)
            order = np.argsort(filtered, axis=0)
            updated = np.empty_like(filtered)
            np.put_along_axis(updated, order, spell.sorted_values, axis=0)
            unchanged = np.array_equal(updated, surrogate)
            surrogate = updated
            if iteration in (30, 100, 300) or unchanged:
                e = np.linalg.norm(np.abs(np.fft.rfft(surrogate, axis=0))-spell.amplitude)
                error[str(iteration)] = float(e / max(float(np.linalg.norm(spell.amplitude)), 1e-12))
                changed_fraction = float(np.mean(surrogate != spell.values))
            if unchanged:
                for checkpoint in (30, 100, 300):
                    if checkpoint >= iteration:
                        error[str(checkpoint)] = error[str(iteration)]
                break
        groups.append({"length": length, "spells": columns, "observations": spell.values.size,
                       "error": error, "iterations": iteration, "fixed_point": unchanged,
                       "changed_fraction": changed_fraction})
    groups.sort(key=lambda item: item["error"]["30"], reverse=True)
    report = {"structure": sid, "cache": cache.name, "mask_observations": int(np.isfinite(x).sum()),
              "expected_observations": row["blades"]["placebo"]["coverage"]["observations"],
              "groups": groups, "seconds": perf_counter()-started,
              "failed_groups": {str(n): sum(g["error"][str(n)] >= .1 for g in groups) for n in (30,100,300)},
              "worst_error": {str(n): max(g["error"][str(n)] for g in groups) for n in (30,100,300)},
              "scope": "One real signal, first surrogate only. Diagnostic, not calibrated inference; no p values."}
    if report["mask_observations"] != report["expected_observations"]:
        raise ValueError("Diagnostic mask differs from original test")
    write_json(ROOT / "artifacts/diagnostics/iaaft-quality-current.json", report)
    print(json.dumps({k:v for k,v in report.items() if k != "groups"}), flush=True)
    print(json.dumps(groups[:8]), flush=True)


if __name__ == "__main__":
    main()