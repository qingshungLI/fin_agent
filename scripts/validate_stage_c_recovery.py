"""Stage C model recovery on fixed synthetic interactions; preview bytes are archived."""
import importlib.util,json
from pathlib import Path
import numpy as np
import pandas as pd
import engine.memory as model
import argparse
parser=argparse.ArgumentParser();parser.add_argument("--seed",type=int,default=734);args=parser.parse_args()
from engine.cache import file_hash
from engine.audit import write_json

path=Path("engine/memory.py")
before=file_hash(path)
rng=np.random.default_rng(args.seed)
family=np.array([-.03,-.015,.015,.03])
forms=np.array([-.02,.005,.015])
interaction=np.outer([-.015,-.008,.008,.015],[-1.,0.,1.])
periods=np.linspace(-.008,.008,8)
records=[];truth={}
for f in range(4):
    truth[("family",f"M{f+1}")]=family[f]
    for v in range(3):
        truth[("form",str(v+1))]=forms[v]
        truth[("interaction",f"M{f+1}:{v+1}")]=interaction[f,v]
        for rep in range(3):
            for period in range(8):
                records.append({"structure":f"{f}-{v}-{rep}","family":f"M{f+1}","form":str(v+1),
                    "period":str(period),"mean":family[f]+forms[v]+interaction[f,v]+periods[period],"se":.006})
frame=pd.DataFrame(records)
after_c=model.build_design_matrix(frame,"C")[0]
assert np.linalg.matrix_rank(after_c)==after_c.shape[1]
same=frame.period.to_numpy()[:,None]==frame.period.to_numpy()[None,:]
covariance=.006**2*(.2*same+.8*np.eye(len(frame)))
frame["mean"]+=rng.multivariate_normal(np.zeros(len(frame)),covariance)
result=model.fit_hierarchy(frame,args.seed,covariance=covariance)
effects=[]
for t in result["terms"]:
    key=(t["group"],t["name"])
    if key not in truth or abs(truth[key])<.004:continue
    true=float(truth[key])
    effects.append({**t,"truth":true,"recovered":bool(t["interpretable"] and t["lower"]*t["upper"]>0
                    and t["mean"]*true>0 and abs(t["mean"]-true)<.01)})
rate=sum(t["recovered"] for t in effects)/len(effects)
assert before==file_hash(path)
report={"passed":result["state"]=="RESEARCH_ONLY" and rate>.7,"recovery":rate,"effects":effects,
        "diagnostics":{k:v for k,v in result.items() if k!="terms"},"source_sha256":before,
        "seed":args.seed,
        "design_after":{"rank":int(np.linalg.matrix_rank(after_c)),"columns":after_c.shape[1]},
        "scope":"single fixed balanced 4x3 interaction scenario, 36 structures and 8 periods; synthetic only",
        "uses_market_data":False}
write_json(Path(f"artifacts/validation/memory-stage-c-recovery-{args.seed}.json"),report)
print(json.dumps({k:v for k,v in report.items() if k!="effects"}),flush=True)
if not report["passed"]:raise SystemExit(2)
