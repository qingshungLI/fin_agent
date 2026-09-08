"""Seeded synthetic statistical diagnostics; no market data or B/H access."""
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import json
import numpy as np
import pandas as pd
from scipy.stats import beta
from engine.config import ResearchConfig
from engine.metrics import summarize, holm
from engine.discovery import blade_icm
from engine.cache import file_hash


def experiment(seed):
    rng = np.random.default_rng(seed)
    c = ResearchConfig(n_boot=1000)
    n = 600
    common = rng.normal(size=n)
    pvalues = []
    for k in range(8):
        noise = .07 * (common + rng.normal(size=n))
        x = np.zeros(n)
        for i in range(1, n):
            x[i] = .4 * x[i-1] + noise[i]
        pvalues.append(summarize(pd.Series(x), 5, c)["p"])
    return int(min(holm(pvalues)) < .05)


def icm_experiment(seed):
    rng = np.random.default_rng(seed)
    n_dates, stocks = 500, 40
    n = n_dates * stocks
    control = rng.normal(size=n)
    signal = .3 * control + rng.normal(size=n)
    moderator = rng.uniform(0, 100, n)
    frame = pd.DataFrame({"date": np.repeat(pd.bdate_range("2010-01-01", periods=n_dates), stocks),
        "symbol": np.tile([f"S{i}" for i in range(stocks)], n_dates), "f": signal,
        "r": .2 * control + .05 * signal + rng.normal(size=n),
        "log_cap": control, "volatility": rng.uniform(.01,.2,n),
        "log_turnover": rng.normal(size=n), "industry": np.tile(["I"+str(i%5) for i in range(stocks)], n_dates),
        "moderator": moderator})
    result = blade_icm(frame, "moderator", 50, 5, ResearchConfig())
    return int(result["p"] < .05)


def main():
    sources=[Path("engine")/n for n in ("metrics.py","discovery.py","config.py","evidence.py")]
    before={p.name:file_hash(p) for p in sources}
    with ProcessPoolExecutor(max_workers=4) as pool:
        fwer = list(pool.map(experiment, range(30000,30200)))
        icm = list(pool.map(icm_experiment, range(40000,40200)))
    report = {"trials": 200, "batch_size": 8,
              "holm_fwer": np.mean(fwer), "icm_null_rejection": np.mean(icm),
              "holm_upper95": float(beta.ppf(.95,sum(fwer)+1,201-sum(fwer))),
              "icm_upper95": float(beta.ppf(.95,sum(icm)+1,201-sum(icm))),
              "scope": "correlated AR(1) null main tests and linear-nuisance ICM; synthetic only"}
    report["passed"] = report["holm_upper95"] < .09 and report["icm_upper95"] < .09
    report["limitations"] = "Does not certify real-data quality, all alternatives, or M9 hierarchy recovery."
    assert before=={p.name:file_hash(p) for p in sources}
    report["code_sha256"]=before
    report["uses_market_data"]=False
    Path("artifacts/validation").mkdir(parents=True, exist_ok=True)
    Path("artifacts/validation/statistics-batch-revised.json").write_text(json.dumps(report,indent=2))
    print(report, flush=True)


if __name__ == "__main__":
    main()
