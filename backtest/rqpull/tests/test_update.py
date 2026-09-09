"""行情更新回归：验证就绪状态和同年重复写入，所有行情均为临时合成数据。"""
from pathlib import Path

import pandas as pd
import pytest

from rqpull.tasks.update import _ready


def test_ready_shapes():
    assert _ready(True)
    assert _ready({"ready": True})
    assert _ready(pd.DataFrame({"ready": [True, True]}))
    assert not _ready(pd.DataFrame({"ready": [True, False]}))


def test_upsert_existing_year_does_not_inject_partition_columns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """同年重复更新保留主键并覆盖价格，假设仅使用隔离合成数据。

    Args:
        tmp_path: pytest 临时目录。
        monkeypatch: 替换数据根目录，不访问真实行情。
    Returns:
        None: 检查新价格、唯一行数及固定字段集合。
    """
    from rqpull import io
    from rqpull.tasks import update

    root = tmp_path / "quoted'path"
    for module in (io, update):
        monkeypatch.setattr(module, "STD_ROOT", root / "standard")
        monkeypatch.setattr(module, "STATE_ROOT", root / "state")
    frame = pd.DataFrame({"date": pd.to_datetime(["2020-01-02"]),
                          "order_book_id": ["000001.XSHE"], "close": [10.]})
    update._upsert_year(frame, 2020)
    target = update._upsert_year(frame.assign(close=12.), 2020)
    result = pd.read_parquet(target)
    assert result.close.tolist() == [12.]
    assert list(result.columns) == list(frame.columns)
    assert not (root / "state/daily_update_2020.parquet").exists()