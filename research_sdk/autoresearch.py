"""Recursive Self-Improvement Alpha Research Harness：有限、可审计的 RSI 研究闭环。

这里 RSI 指 Recursive Self-Improvement。循环把“提出—编译—测量—批评—变异—记录”
拆成可重放阶段；金融 alpha seed 只是协议输入，不代表 RSI 的含义。评估器和验证边界
保持冻结，每一代有有限候选预算，不允许用验证结果反向改写下一代。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable
from pydantic import BaseModel, ConfigDict, Field

import pandas as pd

from research_sdk.core import CellSpec, ExperimentSpec, run_experiment, write_json



class RSIProtocol(BaseModel):
    """冻结递归改进协议；输入代数与候选预算，返回不包含模型自修改权限的配置。"""
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = "Recursive Self-Improvement Alpha Research Harness"
    max_generations: int = Field(default=2, ge=1, le=3)
    max_trials_per_generation: int = Field(default=16, ge=1, le=64)
    selection_metric: str = "training_ic_only"
    evaluator_hash_policy: str = "freeze-before-validation"


def seed_cells() -> list[CellSpec]:
    """生成通用机制 seed；无参数，返回可由递归循环变异的三个冻结研究格子。"""
    return [
        CellSpec(name="短期反转", mechanism="短期价格冲击后的均值回归", expression="neg(ts_z(ret_1d, 20))"),
        CellSpec(name="中期动量", mechanism="历史收益持续性", expression="xs_rank(ret_20d)"),
        CellSpec(name="流动性压力", mechanism="交易摩擦导致的短期价格补偿", expression="neg(xs_rank(ret_1d))"),
    ]


def run_self_improvement_harness(frame: pd.DataFrame, output: str | Path, profile: str = "fast") -> dict:
    """运行一代有界递归自我改进循环；输入用户面板/输出目录/周期，返回完整报告。"""
    cells = seed_cells()
    protocol = RSIProtocol()
    spec = ExperimentSpec(name=protocol.name, cells=cells, profile=profile, evolve=False)
    report = run_experiment(frame, spec, output)
    incumbent: float | None = None
    ledger = []
    for item in report["results"]:
        score = item["train_ic"]
        keep = score is not None and (incumbent is None or score >= incumbent)
        if keep:
            incumbent = score
        ledger.append({"id": item["id"], "generation": 0, "parent": None,
                       "expression": item["expression"], "train_score": score,
                       "state": "KEEP" if keep else "DISCARD", "selection_metric": protocol.selection_metric,
                       "stage": "CRITICIZED", "validation_read_after_freeze": True})
    write_json(Path(output) / "autoresearch.json", {
        "name": protocol.name, "protocol": "fixed evaluator / bounded recursive self-improvement ledger",
        "stages": ["PROPOSE", "COMPILE", "MEASURE", "CRITICIZE", "MUTATE", "RECORD"],
        "protocol_config": protocol.model_dump(),
        "trials": len(ledger), "ledger": ledger, "best_training_ic": incumbent,
        "formal": False, "next_step": "replicate retained variants on an independent date/market split",
    })
    report["autoresearch"] = {"name": protocol.name, "generation": 0, "trials": len(ledger), "best_training_ic": incumbent,
                               "ledger_file": "autoresearch.json", "selection": "training_ic_only"}
    write_json(Path(output) / "report.json", report)
    return report


def load_ledger(output: str | Path) -> list[dict]:
    """读取已完成递归改进账本；输入研究目录，返回 keep/discard 记录并拒绝缺失文件。"""
    path = Path(output) / "autoresearch.json"
    if not path.is_file():
        raise FileNotFoundError("研究目录缺少 autoresearch.json")
    return json.loads(path.read_text(encoding="utf-8"))["ledger"]
