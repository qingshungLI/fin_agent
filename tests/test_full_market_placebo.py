import numpy as np
import pandas as pd
from engine.config import ResearchConfig
from engine import placebo


def test_full_market_keeps_more_than_128_incomplete_securities(monkeypatch):
    rng=np.random.default_rng(3)
    x=pd.DataFrame(rng.normal(size=(200,180)))
    y=pd.DataFrame(rng.normal(size=x.shape))
    for column in range(180):
        x.iloc[100+column%70,column]=np.nan
    allowed=pd.DataFrame(True,index=x.index,columns=x.columns)
    allowed.iloc[100:145,:10]=False
    # This test isolates universe selection; temporal statistics are tested below.
    monkeypatch.setattr(placebo,"temporal_surrogate",lambda x,*args:(x.copy(),0.))
    config=ResearchConfig(mode="engineering",n_placebo=100,workers=2)
    result=placebo.full_market_placebo(x,y,config,eligibility=allowed)
    expected=x.iloc[100:-11].where(allowed.iloc[100:-11]).notna() & y.iloc[100:-11].notna()
    assert result["stocks"]==180
    assert result["coverage"]["stock_cap"] is None
    assert not result["coverage"]["complete_column_filter"]
    assert result["coverage"]["observations"]==int(expected.sum().sum())
    assert result["coverage"]["daily_max"]>128
    assert not expected.all(axis=0).any()


def test_historical_st_values_cannot_enter_surrogate_statistics(monkeypatch):
    rng=np.random.default_rng(2)
    x=pd.DataFrame(rng.normal(size=(140,40)))
    y=pd.DataFrame(rng.normal(size=x.shape))
    allowed=pd.DataFrame(True,index=x.index,columns=x.columns)
    allowed.iloc[80:100,:5]=False
    monkeypatch.setattr(placebo,"temporal_surrogate",lambda x,*args:(x.copy(),0.))
    config=ResearchConfig(mode="engineering",n_placebo=100,workers=1)
    first=placebo.full_market_placebo(x,y,config,eligibility=allowed)
    poisoned=x.mask(~allowed,1e20)
    assert placebo.full_market_placebo(poisoned,y,config,eligibility=allowed)==first


def test_temporal_surrogates_preserve_every_spell_and_gap():
    rng=np.random.default_rng(8)
    x=rng.normal(size=(60,12));x[15:20,:4]=np.nan;x[:8,4:8]=np.nan;x[40:,8:]=np.nan
    plan=placebo.spell_plan(x)
    assert sum(p.values.size for p in plan)==np.isfinite(x).sum()
    for kind in ["time_shift","iaaft"]:
        surrogate,error=placebo.temporal_surrogate(x,plan,np.random.default_rng(9),kind,5)
        assert np.array_equal(np.isnan(x),np.isnan(surrogate))
        for spell in plan:
            np.testing.assert_allclose(np.sort(surrogate.ravel()[spell.positions],axis=0),spell.sorted_values)
        assert np.isfinite(error)


def test_within_day_preserves_daily_full_market_values():
    rng=np.random.default_rng(4)
    x=rng.normal(size=(25,200));x[rng.random(x.shape)<.2]=np.nan
    surrogate=placebo.within_day_surrogate(x,rng)
    assert np.array_equal(np.isnan(x),np.isnan(surrogate))
    for a,b in zip(x,surrogate):
        np.testing.assert_allclose(np.sort(a[np.isfinite(a)]),np.sort(b[np.isfinite(b)]))
