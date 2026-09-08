"""并行发现验证：检查资源边界、真实 spawn 和串行/并行统计输出一致性。

使用合成 A 段数据，不读取生产面板或调用模型；保留真实回归、森林和交互矩检验。
"""

import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from threadpoolctl import threadpool_limits

from engine.config import ResearchConfig
from engine.discovery import evaluate_split
from engine.discovery_parallel import parallel_splits, worker_budget


def test_worker_budget() -> None:
    """检验内存限制与任务上限，无参数，断言并发不会超过预算且低内存仍可串行。"""
    assert worker_budget(3, 2, 2_700_000, 20 * 1024 ** 3) == 2
    assert worker_budget(2, 2, 2_700_000, 11 * 1024 ** 3) == 2
    assert worker_budget(3, 2, 2_700_000, 8 * 1024 ** 3) == 1
    assert worker_budget(3, 2, 2_700_000, 0) == 1
    with pytest.raises(ValueError):
        worker_budget(0, 2, 100, 1024)


def test_spawn_matches_serial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """真实子进程评估固定种子合成样本，返回空，断言 p 值和候选与串行一致。"""
    rng = np.random.default_rng(17)
    dates = pd.bdate_range("2016-07-01", periods=1250).to_numpy()
    size = len(dates) * 100
    signal = rng.normal(size=size)
    moderator = rng.normal(size=size)
    frame = pd.DataFrame({
        "date": np.repeat(dates, 100), "symbol": np.tile(np.arange(100), len(dates)),
        "f": signal, "r": signal * (0.1 + 0.3 * (moderator > 0)) + rng.normal(size=size),
        "log_cap": rng.normal(size=size), "volatility": moderator,
        "log_turnover": rng.normal(size=size), "industry": np.tile(["A", "B"], size // 2),
    })
    config = ResearchConfig(mode="fast", workers=2, n_trees=10, n_splits=2, n_boot=100)
    boundaries = np.array([815, 850])
    cuts = {"vol": {"field": "volatility", "value": 0.0}}
    monkeypatch.setattr("engine.discovery_parallel.available_memory", lambda: 16 * 1024 ** 3)
    monkeypatch.setattr("engine.discovery_parallel.tempfile.tempdir", str(tmp_path))
    with threadpool_limits(limits=1):
        serial = [evaluate_split(
            frame[frame.date.isin(dates[:boundary - 15])].reset_index(drop=True),
            frame[frame.date.isin(dates[boundary:])].reset_index(drop=True),
            ["volatility"], cuts, config, 5, index,
        ) for index, boundary in enumerate(boundaries)]
        parallel = parallel_splits(frame, dates, boundaries, 15, ["volatility"], cuts, config, 5)
    assert not list(tmp_path.iterdir())
    assert any(row["strongest"] is not None for row in serial)
    assert len({row["pid"] for row in parallel}) == 2
    assert all(row["pid"] != os.getpid() for row in parallel)
    assert [row["strongest"] for row in parallel] == [row["strongest"] for row in serial]
    np.testing.assert_allclose([row["p"] for row in parallel], [row["p"] for row in serial], rtol=1e-10)

def test_inplace_nuisance_matches_copying(monkeypatch: pytest.MonkeyPatch) -> None:
    """比较原地与复制式回归，返回空；假设同一输入和训练折，且调用不得修改原始帧。"""
    from engine import discovery

    rng = np.random.default_rng(29)
    size = 240 * 12
    frame = pd.DataFrame({
        "date": np.repeat(pd.bdate_range("2017-01-01", periods=240), 12),
        "symbol": np.tile(np.arange(12), 240), "f": rng.normal(size=size),
        "r": rng.normal(size=size), "x": rng.normal(size=size),
        "industry": np.tile(["A", "B", "C"], size // 3),
    })
    before = frame.copy(deep=True)
    inplace = discovery.orthogonalize(frame, ["x", "industry"])
    original_scaler, original_ridge = discovery.StandardScaler, discovery.Ridge

    def copying_scaler(**kwargs: Any) -> Any:
        """构造复制式 scaler，参数透传并强制 copy，返回基线变换器。"""
        return original_scaler(**{**kwargs, "copy": True})

    def copying_ridge(**kwargs: Any) -> Any:
        """构造复制式 Ridge，参数透传并强制 copy_X，返回基线回归器。"""
        return original_ridge(**{**kwargs, "copy_X": True})

    monkeypatch.setattr(discovery, "StandardScaler", copying_scaler)
    monkeypatch.setattr(discovery, "Ridge", copying_ridge)
    copied = discovery.orthogonalize(frame, ["x", "industry"])
    pd.testing.assert_frame_equal(frame, before)
    np.testing.assert_allclose(inplace[["r_resid", "f_resid"]],
                               copied[["r_resid", "f_resid"]], rtol=1e-12, atol=1e-12)

@pytest.mark.parametrize("available_kib, expected", [(750_000_000, 40), (8_000_000, 1)])
def test_linux_available_memory_includes_reclaimable_cache(monkeypatch, available_kib, expected):
    """Linux 缓存不应误压并发；实际低余量仍限制进程数。"""
    from engine.discovery_parallel import available_memory
    monkeypatch.setattr("engine.discovery_parallel.sys.platform", "linux")
    monkeypatch.setattr(Path, "read_text", lambda self: (
        f"MemFree:        1000000 kB\nMemAvailable: {available_kib} kB\n"))
    result = available_memory()
    assert result == available_kib * 1024
    assert worker_budget(40, 40, 3_000_000, result) == expected


def test_linux_memory_legacy_fallback(monkeypatch):
    """旧内核缺少估算字段时继续使用保守空闲页统计。"""
    from engine.discovery_parallel import available_memory
    monkeypatch.setattr("engine.discovery_parallel.sys.platform", "linux")
    monkeypatch.setattr(Path, "read_text", lambda self: "MemFree: 1000 kB\n")
    monkeypatch.setattr(os, "sysconf", lambda key: {"SC_AVPHYS_PAGES": 123, "SC_PAGE_SIZE": 4096}[key])
    assert available_memory() == 123 * 4096
