"""Fixed synthetic inference validation; never reads market data or confirmation segments."""
import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import beta

from engine.cache import file_hash
from engine.config import ResearchConfig
from engine.discovery import blade_icm


def sample_frame(seed, scenario):
    rng = np.random.default_rng(seed)
    days, stocks = 500, 40
    n = days * stocks
    x = rng.normal(size=n)
    z = pd.Series(x*x).rank(pct=True).to_numpy()*100
    nuisance = x if scenario == "linear_null" else np.sin(x) + .2*x*x if scenario == "smooth_null" else x*x
    f = .8*nuisance + rng.normal(size=n)
    daily = np.zeros(days)
    for i in range(1,days):
        daily[i] = .4*daily[i-1] + rng.normal(scale=.4)
    noise = rng.standard_t(5,n) / np.sqrt(5/3)
    if scenario == "heteroskedastic_null":
        noise *= .5 + np.abs(x)
    r = .7*nuisance + .1*f + noise + np.repeat(daily,stocks)
    if scenario == "interaction_power":
        r += .3*f*np.where(z > 50, 1., -1.)
    return pd.DataFrame({
        "date": np.repeat(pd.bdate_range("2010-01-01",periods=days),stocks),
        "symbol": np.tile([str(i) for i in range(stocks)],days),
        "f": f, "r": r, "log_cap": x, "volatility": rng.uniform(.01,.2,n),
        "log_turnover": rng.normal(size=n),
        "industry": np.tile([str(i%5) for i in range(stocks)],days), "moderator": z})


def trial(item):
    scenario, seed = item
    result = blade_icm(sample_frame(seed,scenario), "moderator", 50, 5, ResearchConfig())
    return scenario, result["p"]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--trials",type=int,default=200)
    parser.add_argument("--seed",type=int,default=91000)
    args=parser.parse_args()
    scenarios=["linear_null","quadratic_null","smooth_null","heteroskedastic_null","interaction_power"]
    jobs=[(case,args.seed+case_index*1000+i) for case_index,case in enumerate(scenarios)
          for i in range(args.trials)]
    values={case:[] for case in scenarios}
    with ProcessPoolExecutor(max_workers=4) as pool:
        for case,p in pool.map(trial,jobs):
            values[case].append(p)
            if len(values[case]) == args.trials:
                print(case, "complete", flush=True)
    rows=[]
    for case,ps in values.items():
        k=int((np.array(ps)<.05).sum()); n=len(ps)
        upper=float(beta.ppf(.95,k+1,n-k)) if k<n else 1.
        lower=float(beta.ppf(.05,k,n-k+1)) if k else 0.
        rows.append({"scenario":case,"trials":n,"rejections":k,"rate":k/n,
                     "lower95":lower,"upper95":upper,
                     "passed":lower>.7 if case=="interaction_power" else upper<.09})
    report={"rows":rows,"passed":all(r["passed"] for r in rows),
            "nominal_alpha":.05,"null_upper95_acceptance":.09,
            "scope":"specified nonlinear/heteroskedastic/date-correlated synthetic cases; not universal certification",
            "code_sha256":{p.name:file_hash(p) for p in Path("engine").glob("*.py")},
            "uses_market_data":False}
    Path("artifacts/validation").mkdir(parents=True, exist_ok=True)
    Path("artifacts/validation/inference-suite.json").write_text(json.dumps(report,indent=2))
    print(json.dumps(rows),flush=True)
    return 0 if report["passed"] else 2

if __name__=="__main__":
    raise SystemExit(main())
