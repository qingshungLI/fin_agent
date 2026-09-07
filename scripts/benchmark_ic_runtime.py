"""Compare bounded-array daily IC with the current implementation on A cache."""
import json
from pathlib import Path
from time import perf_counter
import numpy as np
import pandas as pd
from engine.metrics import daily_ic

def array_daily_ic(factor, returns, minimum=30, rank=False):
    if not factor.index.equals(returns.index) or not factor.columns.equals(returns.columns):
        raise ValueError("因子与收益索引不一致")
    a,b=factor.to_numpy(dtype=float),returns.to_numpy(dtype=float)
    result=np.full(len(a),np.nan)
    for start in range(0,len(a),128):
        x,y=a[start:start+128],b[start:start+128]
        valid=~np.isnan(x)&~np.isnan(y)
        count=valid.sum(axis=1)
        if rank:
            x=pd.DataFrame(np.where(valid,x,np.nan)).rank(axis=1).to_numpy()
            y=pd.DataFrame(np.where(valid,y,np.nan)).rank(axis=1).to_numpy()
        with np.errstate(invalid="ignore",divide="ignore"):
            mx=np.where(valid,x,0).sum(axis=1)/count
            my=np.where(valid,y,0).sum(axis=1)/count
            dx=np.where(valid,x-mx[:,None],0)
            dy=np.where(valid,y-my[:,None],0)
            denom=np.sqrt(np.einsum("ij,ij->i",dx,dx)*np.einsum("ij,ij->i",dy,dy))
            result[start:start+len(x)]=np.divide(np.einsum("ij,ij->i",dx,dy),denom,
                 out=np.full(len(x),np.nan),where=(count>=minimum)&(denom>0))
    return pd.Series(result,index=factor.index)

def main():
    root=Path("artifacts/cache")
    candidates=[]
    for path in root.glob("*/manifest.json"):
        meta=json.loads(path.read_text())
        config=meta["identity"]["config"]
        if config.get("max_symbols")==0 and config.get("industry_source")=="rqdata_daily":
            candidates.append(path.parent)
    assert len(candidates)==1
    path=candidates[0]
    x=pd.read_parquet(path/"fields-ret_5d.parquet")
    y=pd.read_parquet(path/"labels-industry_resid_5.parquet")
    rows=[]
    for rank in [False,True]:
        begin=perf_counter(); old=daily_ic(x,y,rank=rank); old_time=perf_counter()-begin
        begin=perf_counter(); new=array_daily_ic(x,y,rank=rank); new_time=perf_counter()-begin
        assert np.allclose(old,new,equal_nan=True,rtol=0,atol=1e-12)
        rows.append({"rank":rank,"old_seconds":old_time,"new_seconds":new_time,
                     "speedup":old_time/new_time,"max_difference":float((old-new).abs().max())})
    Path("artifacts/validation/ic-array-benchmark.json").write_text(json.dumps(rows,indent=2))
    print(rows,flush=True)

if __name__=="__main__": main()
