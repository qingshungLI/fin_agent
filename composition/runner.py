"""组合批次管线：冻结当前已提交结构与完整 A 段，生成三组固定组合、成本和独立执行任务。

只复制源结构的已提交证据，不占用单结构研究锁、不改其检查点。不按 IC/收益择优。
当前输出全部属于组合研究；各规则、成分和版本在读取组合收益前写入 frozen.json。
"""

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from composition.core import CompositionConfig, compose, holding_path, long_projection
from composition.evaluation import evaluate_targets, transfer_comparison
from engine.audit import now, write_json
from engine.cache import file_hash

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> Any:
    """读取 UTF-8 JSON；参数为已验证本地路径，返回对象，缺失或损坏明确抛错。"""
    return json.loads(path.read_text(encoding="utf-8"))


def source_snapshot(run_id: str, limit: int) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """选择已提交的前 N 个结构并核验来源；输入批次和数量，返回检查点、结构档案、匹配缓存。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", run_id) or limit < 2:
        raise ValueError("组合输入需要合法批次和至少两个结构")
    folder = ROOT / "artifacts" / run_id
    state = load(folder / "checkpoint.json")
    ids = [sid for sid in state["completed"] if sid != state.get("pending_postprocess")][:limit]
    if len(ids) < 2:
        raise ValueError("已提交且完成后处理的结构不足两个")
    rows = {}
    for sid in ids:
        if not re.fullmatch(r"S-[A-Za-z0-9-]+", sid):
            raise ValueError("源结构 ID 非法")
        for name in ("result.json", "frozen.json", "research-factor.parquet"):
            path = folder / sid / name
            key = str(path.relative_to(folder))
            if state["artifact_hashes"].get(key) != file_hash(path):
                raise ValueError(f"源证据未提交或被修改: {key}")
        rows[sid] = load(folder / sid / "result.json")
        if load(folder / sid / "frozen.json")["structure"] != rows[sid]["structure"]:
            raise ValueError("测量结果与冻结规格不一致")
    caches = []
    for path in (ROOT / "artifacts/cache").glob("*/manifest.json"):
        identity = load(path)["identity"]
        if (all(state["identity"]["config"].get(k) == v for k,v in identity["config"].items())
                and all(state["identity"]["code"].get(k) == v for k,v in identity["code"].items())
                and identity["data"] == state["identity"]["sources"]):
            caches.append(path.parent)
    if len(caches) != 1:
        raise ValueError("无法唯一定位原研究数据缓存")
    return state, rows, caches[0]


def cache_field(cache: Path, name: str) -> pd.DataFrame:
    """读取经哈希核验的矩阵；输入缓存和白名单字段名，返回完整矩阵。"""
    path = cache / name
    if load(cache / "manifest.json")["files"].get(name) != file_hash(path):
        raise ValueError(f"缓存损坏: {name}")
    return pd.read_parquet(path)


def execute_snapshot(folder: Path, name: str) -> int:
    """启动真实 RQAlpha 组合目标回放；输入组合目录/规则名，返回退出码并保留完整错误。"""
    with (folder / name / "execution.log").open("w", encoding="utf-8") as log:
        result = subprocess.run([sys.executable, "-u", "-m", "composition.execute", "--target",
            str(folder / name / "target.parquet"), "--output", str(folder / name / "execution")],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=False)
    return result.returncode


def run(run_id: str, batch_id: str, limit: int, execute: bool = False) -> dict[str, Any]:
    """执行一个冻结组合研究批次；输入源批次/新 ID/成分数/执行开关，返回完整状态。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", batch_id):
        raise ValueError("组合批次 ID 非法")
    state, rows, cache = source_snapshot(run_id, limit)
    root = ROOT / "artifacts/compositions"
    folder = root / batch_id
    folder.mkdir(parents=True, exist_ok=False)
    costs = {k:state["identity"]["config"][k] for k in ("commission_bp", "slippage_bp", "stamp_tax_bp")}
    configs = {mode: CompositionConfig(mode=mode, **costs) for mode in ("parallel", "conflict_cash", "consensus")}
    source = ROOT / "artifacts" / run_id
    frozen = {"batch_id": batch_id, "source_run": run_id, "created_at": now(), "source_ids": list(rows),
        "selection": "First completed checkpoint structures, no IC/performance selection", "max_sources": limit,
        "source_identity": state["identity"], "cache_manifest_hash": file_hash(cache / "manifest.json"),
        "source_files": {str((source/sid/name).relative_to(source)): file_hash(source/sid/name)
                         for sid in rows for name in ("frozen.json", "result.json", "research-factor.parquet")},
        "composition_code": {p.name:file_hash(p) for p in (ROOT / "composition").glob("*.py")},
        "variants": {name:asdict(c) for name,c in configs.items()},
        "formal": False, "requires_independent_combination_validation": True,
        "hypotheses": ["parallel: fixed equal-capital paths", "conflict_cash: abstain at opposite signs",
                       "consensus: >=2 distinct constructs with same sign and no opposing construct"],
        "evaluation_dates": "All source A signal dates except last two, reserved for T+1 open and next-open label"}
    write_json(folder / "frozen.json", frozen)
    report = {"batch_id": batch_id, "source_run": run_id, "status": "RUNNING", "formal": False,
        "source_ids": list(rows), "created_at": now(), "variants": {},
        "confirmation": {"status": "BLOCKED", "reason": "New composition rules require independent validation; source exploratory evidence is not formal admission"}}
    write_json(folder / "report.json", report)
    write_json(root / "latest.json", {"batch_id": batch_id})
    try:
        signals = {sid:pd.read_parquet(source / sid / "research-factor.parquet") for sid in rows}
        specs = {sid:row["structure"] for sid,row in rows.items()}
        prototype = next(iter(signals.values()))
        if len(prototype) < 3:
            raise ValueError("完整 A 段不足三日")
        # 组合暴露先固定，随后才读取收益矩阵；截止日期不依赖收益是否有利。
        targets, component_targets = {}, {}
        for name, config in configs.items():
            print(f"composition {name}: combining {len(signals)} sources", flush=True)
            result = compose(signals, specs, config)
            destination = folder / name
            destination.mkdir()
            target = result["target"].iloc[:-2]
            target.to_parquet(destination / "target.parquet")
            result["signed_path"].iloc[:-2].to_parquet(destination / "signed-path.parquet")
            result["daily"].iloc[:-2].to_parquet(destination / "routing-daily.parquet")
            result["contributions"].to_parquet(destination / "contributions.parquet", index=False)
            result["source_routes"].to_parquet(destination / "source-routes.parquet", index=False)
            write_json(destination / "relations.json", result["relations"])
            write_json(destination / "routing.json", {"mode": name, "aliases": result["aliases"],
                "representatives": result["representatives"], "source_gate": "original frozen coverage AND finite source signal",
                "cross_structure_gate": asdict(config), "formal": False,
                "reason_codes": ["OUTSIDE_SOURCE_COVERAGE", "CONFLICT_CASH", "INSUFFICIENT_AGREEMENT", "LONG_ONLY_PROJECTION"]})
            daily = result["daily"].iloc[:-2]
            report["variants"][name] = {"status": "TARGET_READY", "independent_components": len(result["representatives"]),
                "aliases": result["aliases"], "dates": len(target), "symbols": len(target.columns),
                "mean_conflict_stocks": float(daily.conflict_stocks.mean()),
                "mean_gate_closed_stocks": float(daily.gate_closed_stocks.mean()),
                "mean_held_stocks": float(daily.held_stocks.mean()), "mean_exposure": float(daily.long_exposure.mean()),
                "new_hypothesis": name != "parallel", "formal": False}
            targets[name] = target
            if not component_targets:
                for sid in result["representatives"]:
                    frame = signals[sid].reindex(columns=target.columns)
                    path = holding_path(frame, specs[sid]["primary_horizon"], frame.notna())
                    component_targets[sid] = long_projection(path, config).iloc[:-2]
            write_json(folder / "report.json", report)
            print(f"composition {name}: target ready, {len(target)} dates", flush=True)
        opening = cache_field(cache, "fields-open.parquet")
        adjustment = cache_field(cache, "fields-adjustment.parquet")
        adjusted = opening * adjustment
        # 只用于收益诊断；持有资产缺失价格仍导致 INVALID_RETURN_COVERAGE，不按未来可交易性过滤信号。
        forward = (adjusted.shift(-2) / adjusted.shift(-1) - 1).replace([np.inf,-np.inf], np.nan)
        for name, target in targets.items():
            daily, metrics = evaluate_targets(target, forward.reindex_like(target), configs[name])
            daily.to_parquet(folder / name / "research-daily.parquet")
            write_json(folder / name / "cost-comparison.json", transfer_comparison(component_targets, target, configs[name]))
            report["variants"][name].update(status="RESEARCH_MEASURED", metrics=metrics)
            write_json(folder / "report.json", report)
            if execute:
                exit_code = execute_snapshot(folder, name)
                report["variants"][name]["execution"] = {"status": "COMPLETED" if exit_code == 0 else "FAILED", "exit_code": exit_code}
                write_json(folder / "report.json", report)
        report.update(status="RESEARCH_COMPLETED", finished_at=now())
        write_json(folder / "report.json", report)
        write_json(folder / "artifact-hashes.json", {str(p.relative_to(folder)):file_hash(p)
            for p in folder.rglob("*") if p.is_file() and p.name != "artifact-hashes.json"})
        return report
    except BaseException as exc:
        report.update(status="FAILED", error={"type":type(exc).__name__, "message":str(exc)}, finished_at=now())
        write_json(folder / "report.json", report)
        raise


def main() -> int:
    """解析组合 CLI；返回 0 表示研究产物完成，不代表正式确认通过。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--max-sources", type=int, default=6)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.source_run, args.batch_id, args.max_sources, args.execute), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())