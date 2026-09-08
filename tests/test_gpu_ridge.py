import os
import numpy as np
import pytest
from scipy.sparse import csr_matrix
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from engine.config import ResearchConfig


def test_explicit_gpu_and_cpu_budget_configuration():
    cfg=ResearchConfig(mode="fast",workers=40,nuisance_backend="cuda")
    assert ResearchConfig.model_validate(cfg.model_dump())==cfg
    with pytest.raises(ValueError):
        ResearchConfig(workers=41)


@pytest.mark.skipif(os.environ.get("AURORA_TEST_CUDA")!="1",reason="Explicit one-GPU verification required")
def test_real_gpu_matches_centered_multioutput_sparse_ridge(monkeypatch):
    from engine.gpu_ridge import ridge_predict
    monkeypatch.setattr("engine.gpu_ridge.BATCH_ROWS", 127)
    rng=np.random.default_rng(73)
    raw=rng.normal(size=(1500,20));raw[:,1]=raw[:,0];raw[:,2]=1.
    industry=np.eye(8)[np.arange(1500)%8]
    x=csr_matrix(np.column_stack([raw,industry]))
    y=np.column_stack([2+raw[:,0]*.5-raw[:,4]+rng.normal(size=1500)*.01,
                       -3+raw[:,3]*2+rng.normal(size=1500)*.01])
    scaler=StandardScaler(with_mean=False)
    train=scaler.fit_transform(x[:1000]);test=scaler.transform(x[1000:])
    expected=Ridge(alpha=1.,solver="lsqr",tol=1e-10).fit(train,y[:1000]).predict(test)
    actual=ridge_predict(train,y[:1000],test)
    np.testing.assert_allclose(actual,expected,rtol=1e-7,atol=1e-7)


@pytest.mark.skipif(os.environ.get("AURORA_TEST_CUDA")!="1",reason="Explicit one-GPU verification required")
def test_real_gpu_nuisance_residuals_match_cpu_with_same_purged_folds():
    import pandas as pd
    from engine.discovery import orthogonalize
    rng=np.random.default_rng(8);n=240*12
    x=rng.normal(size=n)
    frame=pd.DataFrame({"date":np.repeat(pd.bdate_range("2017-01-01",periods=240),12),
        "symbol":np.tile(np.arange(12),240),"x":x,"industry":np.tile(["A","B","C"],n//3),
        "r":x**2+.1*rng.normal(size=n),"f":np.sin(x)+rng.normal(size=n)})
    before=frame.copy(deep=True)
    cpu=orthogonalize(frame,["x","industry"],"cpu")
    gpu=orthogonalize(frame,["x","industry"],"cuda")
    np.testing.assert_allclose(gpu[["r_resid","f_resid"]],cpu[["r_resid","f_resid"]],rtol=1e-6,atol=1e-7)
    pd.testing.assert_frame_equal(frame,before)
