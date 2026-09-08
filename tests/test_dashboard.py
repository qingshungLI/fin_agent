"""控制台数据契约回归：只读当前批次、真实坐标计数、版本隔离和下载白名单。"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import dashboard_server as dashboard
from engine.audit import write_json


@pytest.fixture
def research(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """构造最小真实形状产物；输入隔离根目录，返回批次目录，不读市场数据。"""
    monkeypatch.setattr(dashboard, "ARTIFACTS", tmp_path)
    folder = tmp_path / "test-run"
    write_json(folder / "checkpoint.json", {"run_id": "test-run", "status": "RUNNING", "completed": [],
        "started_at": "2026-09-08T00:00:00+00:00", "identity": {"config": {"max_structures": 210},
        "code": {"sample.py": "abc"}, "environment": {"python": "3.11"},
        "model": {"model": "test-model", "base_url": "private-endpoint", "api_key": "must-not-leak"}},
        "queue": [{"family": "M2", "form": 3, "operator": "seed"}]})
    (tmp_path / "test-run.stdout.log").write_text(
        "panel ready (1458, 5562), cache=True\nllm proposer: request 1/4200\n"
        "llm proposer: response cached\nprivate token must-not-leak\n", encoding="utf-8")
    return folder


def test_snapshot_is_truthful_and_does_not_publish_private_fields(research: Path) -> None:
    """验证零候选不被虚构，日志和模型输出不包含非白名单字段。"""
    data = dashboard.snapshot("test-run")
    assert data["counts"]["measured"] == 0 and data["counts"]["children"] == 0
    assert len(data["map"]) == 70
    assert data["current"]["cell"] == "M2-F3" and not data["current"]["frozen"]
    assert data["panel"] == {"dates": 1458, "symbols": 5562}
    assert data["log"]["requests"] == 1
    assert "must-not-leak" not in str(data) and "private-endpoint" not in str(data)
    assert data["audit"]["valid"] is None


def test_validation_for_different_code_is_not_reused(research: Path) -> None:
    """保证历史批次不展示其他实现的通过证书；输入隔离批次，输出不可用。"""
    path = research.parent / "validation/full-validation.json"
    write_json(path, {"status": "PASSED", "code_sha256": {"sample.py": "wrong"}, "steps": [{"status": "PASSED"}]})
    assert dashboard.snapshot("test-run")["validation"]["status"] == "UNAVAILABLE"
    write_json(path, {"status": "PASSED", "code_sha256": {"sample.py": "abc"},
                      "environment": {"python": "3.11"}, "steps": []})
    assert dashboard.snapshot("test-run")["validation"]["status"] == "PASSED"


def test_downloads_are_limited_to_public_reports(research: Path) -> None:
    """验证报告下载及缺失、私有文件访问；输入产物，HTTP 明确拒绝越界。"""
    client = TestClient(dashboard.app)
    (research / "report.md").write_text("Research evidence only", encoding="utf-8")
    response = client.get("/api/control/artifact/test-run/report.md")
    assert response.status_code == 200 and "Research evidence" in response.text
    assert client.get("/api/control/artifact/test-run/checkpoint.json").status_code == 404
    assert client.get("/api/control/artifact/test-run/memory.json").status_code == 404
    assert client.get("/api/control/snapshot/missing").status_code == 404
    assert len(client.get("/api/control/runs").json()) == 1

def test_latest_composition_replay_is_scoped_and_pending_is_not_old_success(research: Path) -> None:
    """相同组合只显示本批次最新回放；未启动规则不能继承旧执行成功。"""
    root = research.parent
    write_json(root / "compositions/combo/report.json", {
        "source_run": "test-run", "batch_id": "combo", "variants": {
            "parallel": {"execution": {"status": "COMPLETED"}},
            "consensus": {"execution": {"status": "COMPLETED"}},
        },
    })
    write_json(root / "composition-executions/retry/report.json", {
        "source_run": "test-run", "batch_id": "combo", "created_at": "2026-09-08",
        "variants": {"parallel": {"status": "FAILED", "reason": "Missing execution price"}},
    })
    write_json(root / "composition-executions/other/report.json", {
        "source_run": "other-run", "batch_id": "combo", "created_at": "2026-09-09",
        "variants": {"parallel": {"status": "COMPLETED"}},
    })
    result = dashboard.compositions("test-run")[0]
    assert result["variants"]["parallel"]["execution_failure"] == "Missing execution price"
    assert result["variants"]["consensus"]["execution"]["status"] == "PENDING"
    assert len(result["execution_history"]) == 1
