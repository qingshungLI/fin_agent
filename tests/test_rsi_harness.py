"""递归自我改进账本回归：验证固定 evaluator、训练选择和账本状态。"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest



@pytest.fixture
def panel() -> pd.DataFrame:
    """构造仅供测试的日频长表；输入无，返回 140 日/12 证券面板。"""
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2020-01-01", periods=140)
    close = 20 * np.exp(np.cumsum(rng.normal(0, .02, (140, 12)), axis=0))
    index = pd.MultiIndex.from_product([dates, [f"S{i:02}" for i in range(12)]], names=["date", "symbol"])
    return pd.DataFrame({"open": close.ravel(), "close": (close * 1.001).ravel()}, index=index).reset_index()


def test_self_improvement_harness_writes_training_only_ledger(panel: pd.DataFrame, tmp_path: Path) -> None:
    """固定 alpha seed 产出递归改进账本，keep/discard 只引用训练 IC。"""
    report = __import__("research_sdk").run_self_improvement_harness(panel, tmp_path / "self_improvement")
    ledger = (tmp_path / "self_improvement/autoresearch.json").read_text(encoding="utf-8")
    assert report["name"] == "Recursive Self-Improvement Alpha Research Harness"
    assert report["candidate_count"] == 3
    assert '"selection_metric": "training_ic_only"' in ledger
    assert (tmp_path / "self_improvement/report.json").is_file()