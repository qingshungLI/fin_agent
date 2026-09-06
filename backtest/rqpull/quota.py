from __future__ import annotations

import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import MIN_FREE_DEFAULT, QUOTA_LOG_PATH, ensure_directories


class QuotaExhausted(RuntimeError):
    pass


def quota_snapshot(rqdatac, task: str = "") -> dict:
    quota = None
    last_error = None
    for attempt, delay in enumerate((2, 8, 32, None)):
        try:
            quota = rqdatac.user.get_quota()
            break
        except Exception as exc:
            last_error = exc
            if delay is None:
                raise
            time.sleep(delay)
    if quota is None:
        raise RuntimeError("配额查询失败") from last_error
    limit = float(quota.get("bytes_limit") or 0)
    used = float(quota.get("bytes_used") or 0)
    free = float("inf") if limit == 0 else max(0.0, limit - used)
    record = {
        "time": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "task": task,
        "bytes_limit": limit,
        "bytes_used": used,
        "bytes_free": None if free == float("inf") else free,
        "remaining_days": quota.get("remaining_days"),
        "license_type": quota.get("license_type"),
    }
    ensure_directories()
    with QUOTA_LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        fh.flush()
    return record


def guard(rqdatac, min_free: int = MIN_FREE_DEFAULT, task: str = "") -> float:
    record = quota_snapshot(rqdatac, task)
    free = float("inf") if record["bytes_free"] is None else float(record["bytes_free"])
    if free < min_free:
        raise QuotaExhausted(
            f"剩余配额 {free / 1e6:.0f} MB < 安全垫 {min_free / 1e6:.0f} MB，"
            f"任务 {task} 暂停；次日 00:00 后重跑会从断点继续"
        )
    return free
