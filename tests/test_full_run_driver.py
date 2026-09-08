"""完整运行器回归：校准必须验证来源，空候选必须保持 B/H 未读并落盘阻塞报告。"""

import json
from pathlib import Path

import pytest

from engine.audit import write_json
from engine.cache import file_hash
from scripts import complete_research_run, run_full_validation


def test_calibration_rejects_missing_or_changed_inference_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """校验三套报告及代码哈希；输入临时目录，缺失或篡改不得通过。"""
    engine = tmp_path / "engine"
    engine.mkdir()
    source = engine / "metrics.py"
    source.write_text("original", encoding="utf-8")
    identity = {source.name: file_hash(source)}
    monkeypatch.setattr(run_full_validation, "ROOT", tmp_path)
    folder = tmp_path / "validation"
    folder.mkdir()
    assert not run_full_validation.collect_calibration(folder, identity)["passed"]
    for name in ("statistics-batch-revised.json", "inference-suite.json", "necessary-assertion-suite.json"):
        write_json(folder / name, {"passed": True, "code_sha256": identity, "scope": "fixture"})
    assert run_full_validation.collect_calibration(folder, identity)["passed"]
    source.write_text("modified", encoding="utf-8")
    assert not run_full_validation.collect_calibration(folder, identity)["passed"]


def test_empty_completed_batch_never_consumes_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """模拟已结束的空候选批次；参数为隔离产物，输出明确阻塞而非假通过。"""
    monkeypatch.setattr(complete_research_run, "ROOT", tmp_path)
    artifacts = tmp_path / "artifacts"
    write_json(artifacts / "empty/checkpoint.json", {"status": "COMPLETED", "completed": [],
        "identity": {"config": {"max_structures": 210}}, "confirmation": {"eligible_ids": []}})
    write_json(artifacts / "validation/full-validation.json", {"status": "PASSED", "steps": []})
    write_json(artifacts / "validation/calibration.json", {"passed": True})
    monkeypatch.setattr(complete_research_run, "process_alive", lambda pid: False)
    def forbidden(*args: object, **kwargs: object) -> None:
        """拒绝意外调用确认；输入被忽略，始终抛错以保证 B/H 未读。"""
        raise AssertionError("Confirmation must remain unread")
    monkeypatch.setattr(complete_research_run, "confirm_once", forbidden)
    assert complete_research_run.finish("empty", 1, 2) == 2
    report = json.loads((artifacts / "empty-pipeline/pipeline.json").read_text(encoding="utf-8"))
    assert report["stages"]["B"]["status"] == "BLOCKED"
    assert report["stages"]["research_execution"]["status"] == "BLOCKED"
    assert not report["B_read"] and not report["H_read"]