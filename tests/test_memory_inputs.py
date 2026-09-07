
import numpy as np
import pandas as pd
from engine.memory_inputs import build_memory_inputs


def test_joint_memory_reads_real_export_and_preserves_covariance(tmp_path):
    rng = np.random.default_rng(5)
    dates = pd.bdate_range("2020-01-01", "2020-12-31")
    common = rng.normal(size=len(dates))
    rows = []
    for i in range(2):
        sid = f"S-{i}"
        daily = pd.Series(common + rng.normal(scale=.05, size=len(dates)), index=dates)
        (tmp_path/sid).mkdir()
        pd.DataFrame({"ic_e1_h5": daily}).to_parquet(tmp_path/sid/"daily-ic.parquet")
        quarters = [{"period": str(q), "mean": float(v.mean()), "se": .1}
                    for q,v in daily.groupby(daily.index.to_period("Q"))]
        rows.append({"id":sid,"fingerprint":str(i),"family":"M2","form":1,
            "structure":{"primary_horizon":5},"measurement":{"quarterly":quarters},
            "blades":{"placebo":{"state":"pass"},"assertions":[]}})
    frame,cov,report = build_memory_inputs(rows,tmp_path)
    assert report["state"] == "estimated"
    assert cov.shape == (8,8)
    assert np.linalg.eigvalsh(cov).min() > 0
    assert cov[0,4] > .009
    assert cov[0,1] == 0
    _,_,deduplicated = build_memory_inputs([*rows,dict(rows[0])],tmp_path)
    assert deduplicated["unique_signals"] == 2
    rows[1]["blades"]["assertions"] = [{"kind":"side","state":"violated"}]
    _,_,retracted = build_memory_inputs(rows,tmp_path)
    assert retracted["unique_signals"] == 1


def test_whitening_preserves_correlated_measurement_likelihood():
    from scipy.stats import multivariate_normal, norm
    from engine.memory import whiten_measurements
    rng=np.random.default_rng(91)
    matrix=rng.normal(size=(20,20))
    cov=matrix@matrix.T+np.eye(20)
    y=rng.normal(size=20)
    design=rng.normal(size=(20,7))
    whitened_y,whitened_x=whiten_measurements(y,design,cov)
    logdet=np.linalg.slogdet(cov)[1]/2
    for _ in range(5):
        theta=rng.normal(size=7)
        direct=multivariate_normal.logpdf(y,mean=design@theta,cov=cov)
        transformed=norm.logpdf(whitened_y-whitened_x@theta).sum()-logdet
        np.testing.assert_allclose(direct,transformed,atol=1e-11)
