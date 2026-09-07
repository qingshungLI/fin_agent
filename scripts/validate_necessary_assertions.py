"""Frozen-batch error check when a true main effect has one false necessary assertion."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import json
import numpy as np
import pandas as pd
from scipy.stats import beta
from engine.audit import write_json
from engine.cache import file_hash
from engine.catalog import seed_structure
from engine.blades import blade_assertion
from engine.confirmation import batch_decisions
from engine.config import ResearchConfig
from engine.data import MarketPanel


def experiment(item):
    case,seed=item
    rng=np.random.default_rng(seed)
    config=ResearchConfig()
    days,stocks=500,100
    dates=pd.bdate_range("2010-01-01",periods=days)
    common=rng.normal(size=days)
    common[1:]+=.4*common[:-1]
    rows=[]
    original=seed_structure(0,"null")
    for i in range(8):
        noise=rng.normal(scale=.05,size=days)+.02*common
        noise[1:]+=.4*noise[:-1]
        s=original.model_copy(update={"assertions":[next(a for a in original.assertions if a.kind==case)]})
        x=pd.DataFrame(rng.normal(size=(days,stocks)),index=dates)
        curves={f"ic_e{e}_h{h}":pd.DataFrame({"ic":.2+noise+rng.normal(scale=.03,size=days)},index=dates)
                for e in (1,2,3) for h in (1,3,5,10)}
        fields={}
        if case=="sign":
            curves["ic_e2_h5"]=pd.DataFrame({"ic":noise},index=dates)
            y=x*.2
        elif case=="peak":
            # The best inside and outside horizons tie in expectation.
            for h,mean in [(1,.1),(3,.15),(5,.2),(10,.2)]:
                curves[f"ic_e1_h{h}"]=pd.DataFrame({"ic":mean+noise+rng.normal(scale=.04,size=days)},index=dates)
            y=x*.2
        elif case=="shape":
            bins=np.floor(np.arange(stocks)*5/stocks).astype(int)
            x=pd.DataFrame(np.tile(np.arange(stocks),(days,1)),index=dates)
            effect=np.array([0,.2,.2,.4,.6])[bins]
            shifts=rng.normal(scale=.1,size=(days,5))
            shifts[1:]+=.4*shifts[:-1]
            y=pd.DataFrame(effect+shifts[:,bins]+rng.normal(scale=.3,size=x.shape),index=dates)
        else:
            moderator=s.assertions[0].subject
            fields[moderator]=pd.DataFrame(np.tile([20.]*50+[80.]*50,(days,1)),index=dates)
            y=.2*x+pd.DataFrame(rng.normal(size=x.shape),index=dates)
        panel=MarketPanel(fields,{"industry_resid_5":y},[],{})
        assertion=blade_assertion(s,panel,{"signal_0":x,**curves},config)[0]
        rows.append({"id":str(i),"p":1e-8,"assertions":[assertion]})
    return case,int(any(row["formal"] for row in batch_decisions(rows)))


def main():
    sources=[Path("engine")/p for p in ("blades.py","metrics.py","confirmation.py","config.py")]
    before={p.name:file_hash(p) for p in sources}
    scenarios=("sign","shape","peak","side")
    results={case:[] for case in scenarios}
    with ProcessPoolExecutor(max_workers=4) as pool:
        for case,rejected in pool.map(experiment,[(case,70000+1000*j+i) for j,case in enumerate(scenarios) for i in range(200)]):
            results[case].append(rejected)
            if len(results[case])==200:print(case,"complete",flush=True)
    rows=[]
    for case,values in results.items():
        k,n=sum(values),len(values)
        upper=float(beta.ppf(.95,k+1,n-k)) if k<n else 1.
        rows.append({"false_assertion":case,"trials":n,"false_batches":k,"fwer":k/n,"upper95":upper,"passed":upper<.09})
    assert before=={p.name:file_hash(p) for p in sources}
    report={"rows":rows,"passed":all(r["passed"] for r in rows),"code_sha256":before,
            "batch_size":8,"alpha":.05,"upper95_acceptance":.09,"uses_market_data":False,
            "scope":"one null necessary endpoint per structure with a known strongly positive primary; actual endpoint calculation and frozen-batch decision"}
    write_json(Path("artifacts/validation/necessary-assertion-suite.json"),report)
    print(json.dumps(report),flush=True)
    return 0 if report["passed"] else 2

if __name__=="__main__":raise SystemExit(main())
