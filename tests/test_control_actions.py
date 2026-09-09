"""控制接口回归：在隔离目录验证状态边界、恢复幂等、互斥和失败回滚，不启动研究。"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import dashboard_server as dashboard
from engine.audit import write_json
from engine.pipeline import project_lock


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """创建隔离失败批次，假设不需要实际数据与模型。

    Args:
        tmp_path: pytest 临时目录。
        monkeypatch: pytest 替换工具。
    Returns:
        Path: 新批次目录。
    """
    monkeypatch.setattr(dashboard, "ARTIFACTS", tmp_path)
    folder = tmp_path / "control-test"
    write_json(
        folder / "checkpoint.json", {"run_id": folder.name, "status": "FAILED", "identity": {}}
    )
    return folder


def set_status(folder: Path, status: str) -> None:
    """更新测试检查点，保留其余字段。

    Args:
        folder: 测试批次目录。
        status: 测试状态。
    Returns:
        None: 检查点原子更新。
    """
    state = dashboard.load(folder / "checkpoint.json")
    state["status"] = status
    write_json(folder / "checkpoint.json", state)


@pytest.mark.parametrize("action", ["pause", "stop", "resume", "restart"])
def test_completed_run_rejects_control(run: Path, action: str) -> None:
    """已完成批次不接收控制；输入隔离目录和动作，确认没有产生 sidecar。"""
    set_status(run, "COMPLETED")
    response = TestClient(dashboard.app).post(
        f"/api/control/runs/{run.name}/action", json={"action": action}
    )
    assert response.status_code == 409
    assert not (run / "control.json").exists()


@pytest.mark.parametrize(
    "payload", [{"action": "run"}, {"action": []}, {"action": "stop", "extra": 1}]
)
def test_invalid_action_is_rejected_without_writing(run: Path, payload: dict) -> None:
    """非法输入必须先拒绝；输入 payload，返回明确 HTTP 400 且无文件副作用。"""
    response = TestClient(dashboard.app).post(f"/api/control/runs/{run.name}/action", json=payload)
    assert response.status_code == 400
    assert not (run / "control.json").exists()


def test_pause_is_a_request_not_a_completed_transition(run: Path) -> None:
    """暂停回执保持请求语义；输入目录，检查点仍由引擎负责更新。"""
    set_status(run, "RUNNING")
    result = dashboard.run_action(run.name, {"action": "pause"})
    assert result["status"] == "REQUESTED"
    assert dashboard.load(run / "control.json")["action"] == "pause"
    assert dashboard.load(run / "checkpoint.json")["status"] == "RUNNING"


def test_unknown_pid_does_not_duplicate_a_paused_cli_run(
    run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """外部 CLI 无 PID 时只发送恢复请求；输入目录，不允许擅自另起进程。"""
    set_status(run, "PAUSED")
    monkeypatch.setattr(dashboard, "launch_resume", lambda *args: pytest.fail("unexpected launch"))
    assert dashboard.run_action(run.name, {"action": "resume"})["status"] == "REQUESTED"
    response = TestClient(dashboard.app).post(
        f"/api/control/runs/{run.name}/action", json={"action": "restart"}
    )
    assert response.status_code == 409


def test_duplicate_resume_and_restart_launch_only_once(
    run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """恢复与兼容 restart 共用同一进程；输入隔离目录，重复请求只创建一次子进程。"""
    calls = []
    handles = []

    def launch(*args, **kwargs):
        """模拟 Popen；参数为启动参数，返回固定 PID，不执行任何外部任务。"""
        calls.append(args)
        handles.extend([kwargs["stdout"], kwargs["stderr"]])
        return SimpleNamespace(pid=12345)

    monkeypatch.setattr(dashboard, "validate_resume", lambda state: None)
    monkeypatch.setattr(dashboard.subprocess, "Popen", launch)
    monkeypatch.setattr(dashboard, "process_alive", lambda pid: pid == 12345)
    assert dashboard.run_action(run.name, {"action": "resume"})["status"] == "RESUMING"
    assert dashboard.run_action(run.name, {"action": "restart"})["pid"] == 12345
    assert len(calls) == 1
    assert all(handle.closed for handle in handles)


def test_conflicting_control_request_returns_409(run: Path) -> None:
    """持有控制锁时拒绝另一个请求；输入批次，保证没有写入或重复启动。"""
    with project_lock(run.parent / ".control-locks" / run.name):
        response = TestClient(dashboard.app).post(
            f"/api/control/runs/{run.name}/action", json={"action": "resume"}
        )
    assert response.status_code == 409
    assert not (run / "control.json").exists()


def test_changed_source_rejects_resume_before_control_write(run: Path) -> None:
    """源码不匹配时拒绝恢复；输入空冻结身份，原暂停请求保持不变。"""
    write_json(run / "control.json", {"action": "pause"})
    response = TestClient(dashboard.app).post(
        f"/api/control/runs/{run.name}/action", json={"action": "resume"}
    )
    assert response.status_code == 409
    assert dashboard.load(run / "control.json") == {"action": "pause"}


def test_spawn_failure_restores_previous_control(
    run: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """系统不能创建子进程时恢复原控制记录；输入目录，无 PID 文件残留。"""
    write_json(run / "control.json", {"action": "stop"})

    def fail(*args, **kwargs):
        """模拟系统启动失败；任意参数均抛 OSError，不创建进程。"""
        raise OSError("test spawn failure")

    monkeypatch.setattr(dashboard, "validate_resume", lambda state: None)
    monkeypatch.setattr(dashboard.subprocess, "Popen", fail)
    response = TestClient(dashboard.app).post(
        f"/api/control/runs/{run.name}/action", json={"action": "resume"}
    )
    assert response.status_code == 503
    assert dashboard.load(run / "control.json") == {"action": "stop"}
    assert not (run.parent / f"{run.name}-processes.json").exists()
