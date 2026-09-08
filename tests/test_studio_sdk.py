"""自有数据研究验收：验证输入契约、未来字段防火墙、训练隔离、成本与 HTTP 导出边界。"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_sdk import CellSpec, ExperimentSpec, dataset_summary, run_experiment
from research_sdk.core import backtest, normalize, target_weights
import studio_api


@pytest.fixture
def panel() -> pd.DataFrame:
    """构造仅用于工程测试的面板；无输入，返回 140 日和 12 只证券的可复现价格。"""
    rng = np.random.default_rng(123)
    dates = pd.bdate_range("2020-01-01", periods=140)
    values = 20 * np.exp(np.cumsum(rng.normal(0, .02, (140, 12)), axis=0))
    index = pd.MultiIndex.from_product([dates, [f"S{i:02}" for i in range(12)]], names=["date", "symbol"])
    return pd.DataFrame({"open": values.ravel(), "close": (values * 1.002).ravel()}, index=index).reset_index()


def spec() -> ExperimentSpec:
    """返回有两个可演化起点的配置；无参数，标签方向在看数据前指定。"""
    return ExperimentSpec(cells=[CellSpec(name="反转", mechanism="测试机制", expression="neg(ret_1d)", horizon=3),
                                 CellSpec(name="动量", mechanism="测试机制", expression="ret_5d", horizon=3)])


def test_contract_rejects_duplicate_keys_and_bad_prices(panel: pd.DataFrame) -> None:
    """非法主键和价格不能被自动清洗；输入测试面板，异常必须清晰。"""
    with pytest.raises(ValueError, match="重复"):
        normalize(pd.concat([panel, panel.iloc[:1]]))
    bad = panel.copy(); bad.loc[0, "open"] = 0
    with pytest.raises(ValueError, match="严格为正"):
        normalize(bad)
    assert dataset_summary(panel)["dates"] == 140


def test_validation_prices_do_not_change_parent_selection(panel: pd.DataFrame, tmp_path: Path) -> None:
    """只改变验证段价格不能改变演化来源和训练选定候选；输入面板，输出冻结候选一致。"""
    original = run_experiment(panel, spec(), tmp_path / "original")
    changed = panel.copy()
    boundary = sorted(panel.date.unique())[int(140 * .65)]
    changed.loc[changed.date >= boundary, ["open", "close"]] *= 2
    second = run_experiment(changed, spec(), tmp_path / "changed")
    fields = lambda report: [(r["expression"], r["parent"], r["train_ic"]) for r in report["results"]]
    assert fields(original) == fields(second)
    assert original["selected_id"] == second["selected_id"]
    assert original["candidate_count"] == 6 and not original["formal"]
    assert all("benchmark" in item and "excess_return" in item for item in original["results"])
    assert all(item["closest_training_signal"] is not None for item in original["results"][1:])
    for item in original["results"]:
        if item["quality"] == "REPLICATION_CANDIDATE":
            assert item["ic_interval"][0] > 0 and item["excess_return"] > 0
            assert item["double_cost_return"] > 0
    assert (tmp_path / "original/C001/factor.parquet").is_file()
    with pytest.raises(FileExistsError):
        run_experiment(panel, spec(), tmp_path / "original")


def test_forbidden_expression_is_rejected_before_output(panel: pd.DataFrame, tmp_path: Path) -> None:
    """禁止执行任意 Python 或负滞后；输入非法表达式，不创建研究目录。"""
    for expression in ["__import__('os').getcwd()", "lag(close, -1)", "future_return"]:
        config = ExperimentSpec(cells=[CellSpec(name="bad", mechanism="bad", expression=expression)])
        with pytest.raises(ValueError):
            run_experiment(panel, config, tmp_path / "bad")
        assert not (tmp_path / "bad").exists()


def test_flat_signal_holds_cash_and_missing_returns_invalidate_nav() -> None:
    """常量信号不产生随机持仓；持有收益缺失时不以零填充净值。"""
    frame = pd.DataFrame(1., index=pd.bdate_range("2020-01-01", periods=4), columns=list("AB"))
    assert target_weights(frame).eq(0).all().all()
    target = frame * .05
    returns = frame * .01
    _, low = backtest(target, returns, 5)
    _, high = backtest(target, returns, 10)
    assert high["total_return"] < low["total_return"]
    returns.iloc[1, 0] = np.nan
    daily, missing = backtest(target, returns, 5)
    assert missing["total_return"] is None and daily.nav.isna().all()


def test_api_mapping_and_path_limits(panel: pd.DataFrame, tmp_path: Path, monkeypatch) -> None:
    """使用真实 CSV 映射导入，拒绝跨站和路径注入；输入隔离目录，返回标准摘要。"""
    monkeypatch.setattr(studio_api, "STUDIO", tmp_path)
    app = FastAPI(); app.include_router(studio_api.router)
    client = TestClient(app)
    csv = panel.rename(columns={"symbol": "ticker"}).to_csv(index=False).encode()
    response = client.post('/api/studio/datasets?filename=test.csv&mapping={"symbol":"ticker"}', content=csv)
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    assert client.get("/api/studio/datasets").json()[0]["symbols"] == 12
    assert client.post("/api/studio/datasets", content=csv, headers={"origin": "https://foreign.invalid"}).status_code == 403
    assert client.get(f"/api/studio/experiments/{identifier}/download/private.key").status_code == 404
    invalid = spec().model_dump(); invalid["cells"][0]["expression"] = "lag(close, -1)"
    assert client.post("/api/studio/experiments", json={"dataset_id": identifier, "spec": invalid}).status_code == 422