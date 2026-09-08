"""Fast 条件发现并行管线：长表写入临时 Parquet，独立进程按日期读取切分。

主进程按冻结切分顺序汇总，不把全量 MarketPanel 序列化给子进程。按可用物理内存
保守限制并发；每个进程限制原生线程，防止进程、树线程和 BLAS 叠加抢占资源。
临时数据仅在本次调用期间存在，异常会向上抛出，不生成虚假的中性检验结果。
"""

import ctypes
import multiprocessing
import os
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from engine.config import ResearchConfig


def available_memory() -> int:
    """查询物理内存余量，无参数，返回字节；不支持的平台明确报错。"""
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            """映射 Windows 内存状态结构，无参数，字段单位为字节。"""

            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in (
                    "total_physical", "available_physical", "total_page",
                    "available_page", "total_virtual", "available_virtual", "extended",
                )
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise OSError("Cannot query available physical memory")
        return int(status.available_physical)
    if sys.platform.startswith("linux"):
        # MemAvailable 包含内核估算可回收的缓存；MemFree 会严重低估读过大面板的主机。
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                fields = line.split()
                if len(fields) != 3 or fields[2] != "kB" or int(fields[1]) < 0:
                    raise ValueError("Invalid Linux MemAvailable")
                return int(fields[1]) * 1024
        # 旧内核没有 MemAvailable 时保留原有保守估计。
    return int(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))


def worker_budget(requested: int, splits: int, largest_train: int, free_bytes: int) -> int:
    """按任务数和内存预算返回进程数；参数为并发上限、切分数、行数及可用字节。"""
    if min(requested, splits, largest_train) < 1 or free_bytes < 0:
        raise ValueError("Invalid discovery worker budget")
    # 三个数值控制展开约 43 列；CSR 原地缩放且不保留旧折，含输入预留 1600 B/行。
    # 至少留 2 GiB 给主进程和系统；这是保守调度估计，并非操作系统硬内存限制。
    reserve = 2 * 1024 ** 3
    per_worker = max(512 * 1024 ** 2, largest_train * 1600)
    capacity = max(1, (free_bytes - reserve) // per_worker)
    return min(requested, splits, capacity)


def split_worker(task: dict[str, Any]) -> dict[str, Any]:
    """从 task 中读取日期范围并评估单切分，返回诊断；子进程只读取临时长表。"""
    from engine.discovery import evaluate_split

    with threadpool_limits(limits=1):
        train = pd.read_parquet(task["path"], filters=[("date", "<=", task["train_end"])])
        validation = pd.read_parquet(task["path"], filters=[("date", ">=", task["validation_start"])])
        config = ResearchConfig.model_validate(task["config"]).model_copy(update={"workers": 1})
        return evaluate_split(train.reset_index(drop=True), validation.reset_index(drop=True),
                              task["candidates"], task["cuts"], config, task["horizon"], task["index"])


def parallel_splits(
    frame: pd.DataFrame, dates: np.ndarray, boundaries: np.ndarray, purge: int,
    candidates: list[str], cuts: dict[str, Any], config: ResearchConfig, horizon: int,
) -> list[dict[str, Any]]:
    """调度完整时间切分，返回按输入顺序排列的结果；日期和种子沿用串行定义。

    Args:
        frame: A 段完整案例长表。
        dates: 递增且无重复的日期数组。
        boundaries: 验证起点在 dates 中的索引。
        purge: 训练和验证之间的交易日隔离带。
        candidates: 冻结候选名称。
        cuts: 冻结切点。
        config: 冻结配置，workers 是并发上限。
        horizon: 标签周期，单位为交易日。
    Returns:
        按切分序号汇总的诊断；任一工作进程失败则抛出异常。
    """
    largest_train = int((frame.date <= dates[int(max(boundaries)) - purge - 1]).sum())
    free_bytes = available_memory()
    workers = worker_budget(config.workers, len(boundaries), largest_train, free_bytes)
    print(f"discovery multiprocessing: {workers} processes, {len(boundaries)} splits "
          f"(requested={config.workers}, available={free_bytes / 1024 ** 3:.1f} GiB)", flush=True)
    # 使用唯一临时目录，避免不同研究/测试覆盖输入；spawn 兼容 Windows。
    with tempfile.TemporaryDirectory(prefix="alpha-discovery-") as directory:
        path = Path(directory) / "sample.parquet"
        frame.to_parquet(path, index=False, compression="snappy", row_group_size=100_000)
        tasks = [{"path": str(path), "train_end": pd.Timestamp(dates[int(boundary) - purge - 1]),
                  "validation_start": pd.Timestamp(dates[int(boundary)]),
                  "index": index, "config": config.model_dump(), "candidates": candidates,
                  "cuts": cuts, "horizon": horizon} for index, boundary in enumerate(boundaries)]
        with ProcessPoolExecutor(max_workers=workers,
                                 mp_context=multiprocessing.get_context("spawn")) as pool:
            return list(pool.map(split_worker, tasks))