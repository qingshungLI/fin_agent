import numpy as np
import pandas as pd
import pytest

from engine.data import attach_industry_pit, industry_mean


def test_industry_quarantine_does_not_invent_membership():
    dates = pd.date_range("2020-01-01", periods=5)
    rows = pd.DataFrame([
        ["A", dates[0], dates[4], "X"],
        ["A", dates[2], dates[4], "Y"],
        ["A", dates[0], dates[2], "X"],
    ], columns=["order_book_id", "start_date", "cancel_date", "industry_code"])
    with pytest.raises(ValueError, match="重叠"):
        attach_industry_pit(dates, ["A"], rows)
    result = attach_industry_pit(dates, ["A"], rows, "quarantine")
    assert result.A.iloc[:2].tolist() == ["X", "X"]
    assert result.A.iloc[2:].isna().all()


def test_industry_fast_mean_matches_reference_with_missing():
    rng = np.random.default_rng(3)
    values = pd.DataFrame(rng.normal(size=(50, 100)))
    values.iloc[::3, ::4] = np.nan
    codes = pd.DataFrame(rng.choice(["X", "Y", "Z", None], values.shape))
    reference = pd.DataFrame([
        pd.DataFrame({"value": values.iloc[i], "industry": codes.iloc[i]})
        .groupby("industry").value.transform("mean").to_numpy()
        for i in range(len(values))
    ])
    assert np.allclose(industry_mean(values, codes), reference, equal_nan=True)


def test_panel_cache_reuses_data_across_execution_options(tmp_path, monkeypatch):
    from engine import cache
    from engine.config import ResearchConfig
    from engine.data import MarketPanel
    calls = []
    frame = pd.DataFrame({"A": [1., 2.]})
    def build(*args, **kwargs):
        calls.append(1)
        return MarketPanel({"close": frame}, {"raw_5": frame}, [], {})
    monkeypatch.setattr(cache, "build_panel", build)
    data = tmp_path / "data"
    data.mkdir()
    cfg = ResearchConfig(max_symbols=100)
    _, hit = cache.cached_panel(data, cfg, tmp_path / "cache")
    assert not hit
    _, hit = cache.cached_panel(data, cfg.model_copy(update={"workers": 8, "provider": "llm"}), tmp_path / "cache")
    assert hit and len(calls) == 1
    _, hit = cache.cached_panel(data, cfg.model_copy(update={"cache": False}), tmp_path / "cache")
    assert not hit and len(calls) == 2
    stored = next((tmp_path / "cache").glob("*/fields-close.parquet"))
    stored.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="Corrupt panel"):
        cache.cached_panel(data, cfg, tmp_path / "cache")
    _, hit = cache.cached_panel(data, cfg.model_copy(update={"industry_source": "rqdata_daily"}), tmp_path / "cache")
    assert not hit and len(calls) == 3


def test_daily_industry_join_never_fills_missing_dates():
    from engine.data import attach_daily_industry
    dates = pd.date_range("2021-07-29", periods=3)
    daily = pd.DataFrame({
        "order_book_id": ["A", "A"], "date": dates[[0,2]],
        "third_industry_code": ["OLD", "NEW"], "source": ["sws"]*2,
        "client_version": ["3.5.6.1"]*2, "retrieved_at": [pd.Timestamp("2026-09-07",tz="UTC")]*2})
    result = attach_daily_industry(dates, ["A"], daily)
    assert result.A.iloc[0] == "OLD"
    assert pd.isna(result.A.iloc[1])
    assert result.A.iloc[2] == "NEW"
    with pytest.raises(ValueError, match="主键"):
        attach_daily_industry(dates, ["A"], pd.concat([daily,daily]))
    with pytest.raises(ValueError, match="来源"):
        attach_daily_industry(dates, ["A"], daily.assign(source="unknown"))

