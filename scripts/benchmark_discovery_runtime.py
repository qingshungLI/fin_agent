"""Independent dense/sparse and forest regression on a seeded synthetic panel."""
import importlib.util
import json
from pathlib import Path
from time import perf_counter
import numpy as np
import pandas as pd
from engine.config import ResearchConfig

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod

def main():
    root=Path("artifacts/validation")
    old=load("reference",root/"discovery-reference-before-sparse.py")
    new=load("candidate",root/"discovery-sparse-candidate.py")
    rng=np.random.default_rng(183)
    days,stocks=1000,120
    n=days*stocks
    control=rng.normal(size=n);f=.3*control+rng.normal(size=n);z=rng.uniform(0,100,n)
    frame=pd.DataFrame({"date":np.repeat(pd.bdate_range("2010-01-01",periods=days),stocks),
        "symbol":np.tile([f"S{i}" for i in range(stocks)],days),"f":f,
        "r":.2*control+(.05+.2*(z>50))*f+rng.normal(size=n),
        "log_cap":control,"volatility":rng.uniform(.01,.2,n),"log_turnover":rng.normal(size=n),
        "industry":np.tile([f"I{i%30}" for i in range(stocks)],days),"moderator":z})
    controls=["log_cap","volatility","log_turnover","industry"]
    t=perf_counter(); a=old.orthogonalize(frame,controls); t_old=perf_counter()-t
    t=perf_counter(); b=new.orthogonalize(frame,controls); t_new=perf_counter()-t
    err=float(np.max(np.abs(a[["f_resid","r_resid"]].to_numpy()-b[["f_resid","r_resid"]].to_numpy())))
    assert err<1e-7,err
    config=ResearchConfig()
    cuts={"median":{"field":"moderator","value":50,"side":"high"}}
    t=perf_counter(); left=old.forest_propose(frame,["moderator"],cuts,config); forest_old=perf_counter()-t
    t=perf_counter(); right=new.forest_propose(frame,["moderator"],cuts,config); forest_new=perf_counter()-t
    assert left["valid_trees"]==right["valid_trees"]
    assert left["candidates"]==right["candidates"]
    np.testing.assert_allclose(left["internal_leaf_effects"],right["internal_leaf_effects"],atol=1e-7,rtol=0)
    result={"max_residual_error":err,"dense_seconds":t_old,"sparse_seconds":t_new,
            "forest_old_seconds":forest_old,"forest_new_seconds":forest_new,
            "valid_trees":right["valid_trees"],"trees":config.n_trees,
            "scope":"Seeded synthetic equivalence check; not comprehensive statistical calibration"}
    (root/"discovery-performance.json").write_text(json.dumps(result,indent=2))
    print(result,flush=True)

if __name__=="__main__":main()
