"""工程回归：验证写入互斥、异常退出恢复，以及安慰剂失败后跳过昂贵计算。"""

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from engine.config import ResearchConfig
from engine.pipeline import project_lock
from engine import placebo


def test_lock_recovers_after_process_exit(tmp_path: Path) -> None:
    """验证子进程异常退出后可重入。

    Args:
        tmp_path: pytest 隔离目录，不接触真实研究锁。
    Returns:
        None: 通过断言验证互斥和退出恢复，要求使用当前 Python。
    """
    script = (
        "import os,sys; from pathlib import Path; "
        "from engine.pipeline import project_lock; "
        "lock=project_lock(Path(sys.argv[1])); lock.__enter__(); "
        "print('locked',flush=True); sys.stdin.readline(); os._exit(0)"
    )
    child = subprocess.Popen(
        [sys.executable, "-u", "-c", script, str(tmp_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert child.stdout.readline().strip() == "locked"
        with pytest.raises(RuntimeError, match="Another research writer"):
            with project_lock(tmp_path):
                pytest.fail("两个进程同时进入写入区间")
        child.communicate(input="exit\n", timeout=20)
        assert child.returncode == 0
        with project_lock(tmp_path):
            assert (tmp_path / ".run.lock").exists()
        with pytest.raises(ValueError, match="controlled"):
            with project_lock(tmp_path):
                raise ValueError("controlled")
        with project_lock(tmp_path):
            pass
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=20)


def test_failed_placebo_skips_temporal_work(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证失败后的昂贵检验不执行且明确标注。

    Args:
        monkeypatch: pytest 替换工具，仅截获时间替代计算。
    Returns:
        None: 用独立噪声稳定触发首检验失败，保留全部重复次数。
    """
    def forbidden(*args: object) -> None:
        """拒绝时间检验调用；参数为测试替身输入，返回前直接报错。"""
        raise AssertionError("失败后不应执行时间替代检验")

    rng = np.random.default_rng(42)
    signal = pd.DataFrame(rng.normal(size=(180, 40)))
    monkeypatch.setattr(placebo, "temporal_surrogate", forbidden)
    config = ResearchConfig(mode="engineering", n_placebo=100, workers=2)
    result = placebo.full_market_placebo(signal, pd.DataFrame(rng.normal(size=signal.shape)), config)
    assert result["state"] == "fail"
    assert result["skipped_tests"] == ["time_shift", "iaaft"]
    assert len(result["tests"]) == 1
    assert len(result["tests"][0]["null"]) == 100


def test_invalid_surrogate_stops_without_rejecting_factor(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证替代样本质量失败不会冒充因子反证。

    Args:
        monkeypatch: pytest 替换工具，使前两项通过并注入无效频谱。
    Returns:
        None: 仅无效 IAAFT 提前停止，且不报告伪造的 p 值。
    """
    calls = []

    def surrogate(x: np.ndarray, plan: object, rng: object,
                  kind: str, horizon: int) -> tuple[np.ndarray, float]:
        """构造受控替代样本；输入测试面板等参数，返回反向信号和固定质量误差。"""
        calls.append(kind)
        return np.roll(x, 17, axis=0), 0.2 if kind == "iaaft" else 0.0

    rng = np.random.default_rng(8)
    signal = pd.DataFrame(rng.normal(size=(180, 40)))
    monkeypatch.setattr(placebo, "temporal_surrogate", surrogate)
    config = ResearchConfig(mode="engineering", n_placebo=100, workers=2)
    result = placebo.full_market_placebo(signal, signal, config)
    assert result["state"] == "untested"
    assert result["stopped_early"]
    assert result["tests"][-1]["p"] is None
    assert calls.count("time_shift") == 100
    assert calls.count("iaaft") == 2
