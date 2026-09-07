"""Known-effect recovery of the covariance-aware research memory; synthetic only."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from engine.memory import fit_hierarchy
from engine.cache import file_hash

def main():
    identity={p.name:file_hash(p) for p in [Path("engine/memory.py"),Path(__file__)]}
    reports=[]
    for seed in (731,732,733):
        rng=np.random.default_rng(seed)
        families=np.array([-.03,-.015,.015,.03])
        forms=np.array([-.02,.005,.015])
        periods=np.linspace(-.008,.008,8)
        rows=[]
        truth={}
        for f in range(4):
            truth[("family",f"M{f+1}")]=families[f]
            for v in range(3):
                truth[("form",str(v+1))]=forms[v]
                for rep in range(2):
                    for period in range(8):
                        rows.append({"structure":f"{f}-{v}-{rep}","family":f"M{f+1}","form":str(v+1),
                            "period":str(period),"mean":families[f]+forms[v]+periods[period],"se":.006})
        frame=pd.DataFrame(rows)
        same=frame.period.to_numpy()[:,None] == frame.period.to_numpy()[None,:]
        covariance=.006**2*(.2*same+.8*np.eye(len(frame)))
        frame["mean"]+=rng.multivariate_normal(np.zeros(len(frame)),covariance)
        result=fit_hierarchy(frame,seed,covariance=covariance)
        effects=[]
        for t in result["terms"]:
            key=(t["group"],t["name"])
            if key not in truth: continue
            true=float(truth[key])
            effects.append({**t,"truth":true,"recovered":bool(t["interpretable"] and
                t["lower"]*t["upper"]>0 and t["mean"]*true>0 and abs(t["mean"]-true)<.01)})
        rate=sum(t["recovered"] for t in effects)/len(truth)
        record={"seed":seed,"recovery":rate,"passed":result["state"]=="RESEARCH_ONLY" and rate>.7,
            "effects":effects,"diagnostics":{k:v for k,v in result.items() if k!="terms"}}
        reports.append(record)
        print(json.dumps({k:v for k,v in record.items() if k!="effects"}),flush=True)
        Path("artifacts/validation/memory-recovery.json").write_text(json.dumps(
            {"runs":reports,"passed":len(reports)==3 and all(r["passed"] for r in reports),
            "code_sha256":identity,"scope":"balanced 4x3, two replicate structures, 8 periods, known joint measurement covariance; not universal recovery",
            "criterion":"each run >70% known family/form effects: interpretable, correct nonzero interval sign, mean error <.01",
            "uses_market_data":False},indent=2))
    assert identity == {p.name:file_hash(p) for p in [Path("engine/memory.py"),Path(__file__)]}
    return 0 if all(r["passed"] for r in reports) else 2

if __name__=="__main__": raise SystemExit(main())
