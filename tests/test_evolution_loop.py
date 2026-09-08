"""演化回归管线：验证交叉提案、防火墙、覆盖预算、续接完整性和条件发现的有效切分。"""

import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from engine.audit import write_json
from engine.cache import file_hash
from engine.catalog import seed_structure
from engine.config import ResearchConfig
from engine.continuation import inherit_research, prioritize_queue
from engine.cycle import ProposalTask, followup_tasks, initial_tasks, prior_hint
from engine.discovery import repeat_splits


def row(index: int) -> dict:
    """构造控制研究档案；输入种子序号，返回带合成支持证据的结构，不含真实市场结论。"""
    spec = seed_structure(index, "testloop").model_dump()
    return {"id": spec["id"], "family": spec["family"], "form": spec["form"],
            "structure": spec, "verdict": "UNDECIDABLE", "power": {"main_mde": .01},
            "measurement": {"coverage": .8}, "blades": {"placebo": {"state": "pass"},
            "assertions": [{"kind": "side", "state": "hold", "subject": "market_cap_pct"}]}}


def test_crossover_does_not_leak_donor_outcomes() -> None:
    """验证交叉仅借变量名；无参数，返回 None，供体支持仅用于程序调度。"""
    target, donor = row(0), row(2)
    donor["structure"]["lineage"] = {"moderator": "market_cap_pct"}
    task = ProposalTask.model_validate(followup_tasks(target, [target, donor])["tasks"][0])
    assert task.operator == "crossover" and task.donor == donor["id"]
    hint = prior_hint(task, target)
    assert hint["moderator"] == "market_cap_pct"
    assert "measurement" not in hint["parent_specification"]
    assert "blades" not in hint and "donor_specification" not in hint
    donor["blades"]["assertions"][0]["state"] = "untested"
    assert followup_tasks(target, [target, donor])["tasks"] == []
    donor["blades"]["assertions"][0]["state"] = "hold"
    target["structure"]["lineage"]["depth"] = 2
    assert followup_tasks(target, [target, donor])["tasks"] == []


def test_seed_budget_survives_large_child_queue() -> None:
    """验证有限预算先保住地图覆盖；无参数，返回 None，孩子不抢占最后的种子额度。"""
    seeds = [t.model_dump() for t in initial_tasks()]
    child = ProposalTask(family="M2", form=6, parent="S-test-1", moderator="market_cap_pct",
                         operator="forest", depth=1).model_dump()
    queue = [deepcopy(child) for _ in range(20)] + seeds
    visited = []
    for remaining in range(70, 0, -1):
        prioritize_queue(queue, remaining, 5)
        visited.append(queue.pop(0))
    assert all(t["operator"] == "seed" for t in visited)
    assert len({(t["family"], t["form"]) for t in visited}) == 70
    queue = [child, *seeds]
    prioritize_queue(queue, 210, 5)
    assert queue[0]["operator"] == "forest"


def parent_run(root: Path) -> dict:
    """建立带哈希的父运行；输入隔离根目录，返回身份，测试不接触真实审计库。"""
    folder = root / "parent"
    target = folder / "S-parent-001"
    target.mkdir(parents=True)
    for name in ("result.json", "frozen.json", "daily-ic.parquet", "research-factor.parquet"):
        (target / name).write_bytes(b"fixture")
    identity = {"code": {"engine": "same"}, "sources": {}, "data_root": str(root),
                "model": {"name": "fixture"},
                "config": ResearchConfig(provider="llm").model_dump()}
    hashes = {str(p.relative_to(folder)): file_hash(p) for p in target.iterdir()}
    write_json(folder / "checkpoint.json", {"identity": identity, "status": "COMPLETED",
               "completed": [target.name], "artifact_hashes": hashes, "queue": [], "queued_keys": []})
    return identity


def test_continuation_copies_verified_evidence_and_preserves_origin(tmp_path: Path) -> None:
    """验证续接身份和篡改拒绝；参数为临时目录，返回 None，旧证据不计新完成数。"""
    identity = parent_run(tmp_path)
    folder = tmp_path / "next"
    folder.mkdir()
    result = inherit_research(tmp_path, folder, "parent", identity)
    assert result["inherited"] == ["S-parent-001"]
    assert result["attempts"] == 0
    assert result["source_runs"]["S-parent-001"] == "parent"
    assert (folder / "S-parent-001" / "result.json").read_bytes() == b"fixture"
    other = tmp_path / "other"
    other.mkdir()
    changed = deepcopy(identity)
    changed["config"]["n_boot"] = 100
    with pytest.raises(ValueError, match="statistical"):
        inherit_research(tmp_path, other, "parent", changed)
    (tmp_path / "parent" / "S-parent-001" / "result.json").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="changed"):
        inherit_research(tmp_path, other, "parent", identity)


def test_all_discovery_splits_have_valid_date_budgets(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证全部二十次切分执行且使用登记周期；输入替换工具，返回 None，不缩减折数。"""
    import engine.discovery as discovery
    frame = pd.DataFrame({"date": pd.bdate_range("2010-01-01", periods=1458)})
    horizons, counts = [], []

    def sample(panel: object, signal: object, horizon: int, candidates: list) -> pd.DataFrame:
        """记录采样周期；参数来自发现接口，返回固定日期样本。"""
        horizons.append(horizon)
        return frame

    def forest(training: pd.DataFrame, *args: object) -> dict:
        """记录训练长度；输入训练样本，返回一个固定候选以验证调度。"""
        counts.append(training.date.nunique())
        return {"candidates": [{"name": "market_cap_pct", "frequency": 1.0}]}

    def icm(validation: pd.DataFrame, name: str, cut: float, horizon: int, config: object) -> dict:
        """核对验证长度与周期；参数为冻结检验输入，返回控制 p 值。"""
        assert validation.date.nunique() >= 400 and horizon == 10
        return {"p": .001}

    monkeypatch.setattr(discovery, "make_sample", sample)
    monkeypatch.setattr(discovery, "forest_propose", forest)
    monkeypatch.setattr(discovery, "blade_icm", icm)
    result = repeat_splits(None, None, ["market_cap_pct"],
                          {"cut": {"field": "market_cap_pct", "value": 50}}, ResearchConfig(), horizon=10)
    assert horizons == [10] and len(counts) == 20 and min(counts) >= 800
    assert result["selection_frequency"]["market_cap_pct"] == 1
    assert len(result["fold_p"]) == 20


@pytest.mark.parametrize("interrupt_hook", [False, True])
def test_pipeline_executes_frozen_child_and_resumes_without_remeasurement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupt_hook: bool,
) -> None:
    """验证父子结构真正通过管线闭环。

    Args:
        tmp_path: 隔离的审计和结果目录。
        monkeypatch: 替换昂贵统计与模型；保留实际调度、冻结、持久化和恢复。
    Returns:
        None: 两个独立冻结 ID、子结构谱系及一次性测量必须成立。
    """
    from engine import pipeline
    from engine.catalog import FORM_CODES
    from engine.data import MarketPanel
    from engine.audit import AuditStore

    (tmp_path / "engine").mkdir()
    data = tmp_path / "data"
    data.mkdir()
    dates = pd.bdate_range("2020-01-01", periods=100)
    values = pd.DataFrame(np.random.default_rng(1).normal(size=(100, 40)), index=dates)
    fields = {"close": values, "in_pool": values.notna()}
    panel = MarketPanel(fields, {}, [])
    calls, hints = [], []
    failures = []

    class Model:
        """提供受控事前档案；输入缓存配置，输出固定模型响应，不读收益。"""
        def __init__(self, *args: object, **kwargs: object) -> None:
            """忽略测试缓存参数；返回 None，响应由固定规则生成。"""
        def configuration_identity(self) -> dict:
            """返回固定模型身份；无参数，返回字典。"""
            return {"model": "controlled"}
        def propose(self, cell: dict, run_id: str, index: int,
                    names: set, cuts: dict, hint: dict) -> object:
            """返回父或子事前提案；输入队列上下文，返回完整结构。"""
            hints.append(hint)
            spec = seed_structure(0, run_id).model_copy(deep=True)
            spec = spec.model_copy(update={"id": f"S-{run_id}-{index+1:03d}"})
            if index:
                labels = {**spec.labels, "form": FORM_CODES[5]}
                spec = spec.model_copy(update={"form": 6, "labels": labels,
                    "coverage": "in_pool and (gate(market_cap_pct, 'cut') == 1)",
                    "lineage": {**hint, "origin": "forest", "search_condition": True}})
            return spec
        def bets(self, spec: object) -> dict:
            """返回固定盲押；参数为未测量提案，返回概率字典。"""
            return {a.id: {"probability": .6} for a in spec.assertions}
        def request(self, role: str, context: dict, instruction: str) -> dict:
            """返回逐断言确定性核对；参数为角色与结果上下文，返回三分组。"""
            if interrupt_hook and not failures:
                failures.append(role)
                raise RuntimeError("injected postprocessing outage")
            assert role == "reconciler"
            return {"aligned": [a["id"] for a in context["assertion_results"]],
                    "divergent": [], "unresolved": []}

    def measure(spec: object, *args: object) -> tuple:
        """测量前核对冻结已存在；输入结构，返回受控统计及日信号。"""
        assert (tmp_path / "artifacts" / "loop" / spec.id / "frozen.json").exists()
        calls.append(spec.id)
        summary = {"expression": 1, "horizon": 5, "mean": .05, "n_eff": 100000,
                   "ci_low": .03, "ci_high": .07}
        return {"curves": [summary], "quarterly": [], "coverage": .8}, {
            "signal_0": values, "contribution": values,
            "ic_e1_h5": pd.DataFrame({"ic": values.mean(axis=1)})}

    def blades(spec: object, *args: object) -> dict:
        """生成支持的必要断言；输入结构，返回受控检验结果以触发条件发现。"""
        return {"verdict": "UNDECIDABLE", "placebo": {"state": "pass"},
                "assertions": [{"id": a.id, "kind": a.kind, "subject": a.subject, "state": "hold"}
                               for a in spec.assertions], "increment": {"state": "not_applicable"}}

    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    monkeypatch.setattr(pipeline, "DeepSeek", Model)
    monkeypatch.setattr(pipeline, "cached_panel", lambda *args: (panel, False))
    monkeypatch.setattr(pipeline, "freeze_cuts", lambda *args: {})
    monkeypatch.setattr(pipeline, "register_cell", lambda *args: {})
    monkeypatch.setattr(pipeline, "check_convergent_orientation", lambda *args: {})
    monkeypatch.setattr(pipeline, "measure_panel", measure)
    monkeypatch.setattr(pipeline, "run_blades", blades)
    monkeypatch.setattr(pipeline, "stability", lambda *args: {"consistent": True})
    monkeypatch.setattr(pipeline, "cost_report", lambda *args: {"net_top_excess_mean": .01})
    monkeypatch.setattr(pipeline, "variance_vs_mean_screen", lambda *args: {"mean_shift": ["market_cap_pct"]})
    monkeypatch.setattr(pipeline, "repeat_splits", lambda *args, **kwargs: {
        "p_median": .001, "selection_frequency": {"market_cap_pct": .95}})
    monkeypatch.setattr(pipeline, "initial_tasks", lambda: [initial_tasks()[0]])
    config = ResearchConfig(provider="llm", max_structures=2)
    if interrupt_hook:
        with pytest.raises(RuntimeError, match="injected postprocessing outage"):
            pipeline.run_research(config, "loop", data, tmp_path / "artifacts", discovery=True)
        failed = json.loads((tmp_path / "artifacts/loop/checkpoint.json").read_text(encoding="utf-8"))
        assert len(calls) == 1 and len(failed["completed"]) == 1
        assert failed["pending_postprocess"] == calls[0]
    state = pipeline.run_research(config, "loop", data, tmp_path / "artifacts", discovery=True)
    assert state["status"] == "COMPLETED" and len(state["completed"]) == 2
    assert hints[1]["operator"] == "forest"
    assert hints[1]["parent"] == calls[0]
    assert "mean_shift" not in str(hints[1]) and "p_median" not in str(hints[1])
    assert len(AuditStore(tmp_path / "artifacts").verify()["access"]) == 0
    again = pipeline.run_research(config, "loop", data, tmp_path / "artifacts", discovery=True)
    assert again == state and len(calls) == 2
