"""Fast 配置回归：减少检验只改变探索调度，正式资格和法则证据仍受完整检验约束。"""
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from engine.config import ResearchConfig
from engine.cycle import followup_tasks, observation_laws
from engine.placebo import full_market_placebo
from engine.pipeline import eligibility
from test_evolution_loop import row


def test_fast_placebo_is_diagnostic_and_never_calls_temporal_surrogates(monkeypatch) -> None:
    """输入全截面小面板，验证实际重复次数和跳过项，输出始终未正式检验。"""
    import engine.placebo as placebo

    def forbidden(*args, **kwargs):
        """拒绝昂贵时间替代调用；测试替身忽略参数并抛错。"""
        raise AssertionError("Fast unexpectedly invoked temporal work")

    monkeypatch.setattr(placebo, "spell_plan", forbidden)
    monkeypatch.setattr(placebo, "temporal_surrogate", forbidden)
    rng = np.random.default_rng(9)
    signal = pd.DataFrame(rng.normal(size=(180, 12)))
    config = ResearchConfig(mode="fast", n_placebo=9, min_cross_section=10, workers=1)
    result = full_market_placebo(signal, signal.copy(), config)
    assert result["state"] == "untested" and result["profile"] == "fast"
    assert len(result["tests"]) == 1 and len(result["tests"][0]["null"]) == 9
    assert result["skipped_tests"] == ["time_shift", "iaaft"]


def test_fast_children_do_not_turn_unresolved_parents_into_laws() -> None:
    """未通过安慰剂的父结构可探索生成子结构，但不能成为机制法则或无限繁殖。"""
    parent = deepcopy(row(0))
    parent["blades"]["placebo"]["state"] = "untested"
    parent["power"] = {"main_mde": 1.0}
    assert followup_tasks(parent, [parent])["tasks"] == []
    result = followup_tasks(parent, [parent], exploratory=True)
    assert result["tasks"] and result["exploratory"]
    assert result["tasks"][0]["parent"] == parent["id"]
    assert observation_laws([parent]) == []
    parent["structure"]["lineage"]["depth"] = 2
    assert followup_tasks(parent, [parent], exploratory=True)["tasks"] == []


def test_fast_cannot_enter_confirmation_even_with_other_checks_passed() -> None:
    """全部人工检查为通过时 fast 仍不能晋级，完整模式仍拒绝低重复次数。"""
    candidate = row(0)
    candidate.update(stability={"consistent": True}, cost={"net_top_excess_mean": .1})
    candidate["blades"]["increment"] = {"state": "pass"}
    result = eligibility(candidate, ResearchConfig(mode="fast"), [])
    assert not result["eligible"] and "fast mode" in result["reasons"]
    with pytest.raises(ValueError, match="正式模式"):
        ResearchConfig(n_placebo=19)

def test_fast_composition_milestones_run_distinct_sizes_without_waiting(tmp_path, monkeypatch) -> None:
    """固定完成节点依次触发 4/8/16 成分回测；输入隔离目录，输出不同冻结批次。"""
    import json
    import sys
    from types import SimpleNamespace
    from engine.audit import write_json
    from scripts import watch_fast_compositions as watcher

    monkeypatch.setattr(watcher, "ROOT", tmp_path)
    write_json(tmp_path / "artifacts/fast-test/checkpoint.json", {
        "completed": [f"S-{i}" for i in range(17)], "pending_postprocess": "S-16",
    })
    commands = []

    def execute(command, **kwargs):
        """记录启动参数并模拟独立报告；输入命令，返回退出码，不运行市场回测。"""
        commands.append(command)
        batch = command[command.index("--batch-id") + 1]
        write_json(tmp_path / "artifacts/compositions" / batch / "report.json", {
            "status": "RESEARCH_COMPLETED", "variants": {
                "parallel": {"execution": {"status": "FAILED"}},
            },
        })
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(watcher.subprocess, "run", execute)
    monkeypatch.setattr(watcher, "process_alive", lambda pid: False)
    monkeypatch.setattr(sys, "argv", ["watch", "--run-id", "fast-test", "--research-pid", "123"])
    assert watcher.main() == 0
    assert [c[c.index("--max-sources") + 1] for c in commands] == ["4", "8", "16"]
    assert all("--execute" in c for c in commands)
    report = json.loads((tmp_path / "artifacts/fast-test-composition-watch.json").read_text())
    assert all(v["execution"]["parallel"]["status"] == "FAILED" for v in report["batches"].values())
def test_fast_llm_crash_has_explicit_deterministic_fallback() -> None:
    """fast 研究允许记录模型崩溃后继续，但正式配置仍需抛出错误。"""
    import inspect
    from engine import pipeline
    source = inspect.getsource(pipeline._run)
    assert 'CRASH_RECORDED' in source and 'config.mode != "fast"' in source