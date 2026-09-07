"""Strong synthetic interaction runtime check; never reads market data."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from engine.config import ResearchConfig
from engine.discovery import forest_propose, blade_icm

rng = np.random.default_rng(918)
dates, stocks = 1000, 120
n = dates * stocks
control = rng.normal(size=n)
factor = .3 * control + rng.normal(size=n)
moderator = rng.uniform(0, 100, n)
frame = pd.DataFrame({
    "date": np.repeat(pd.bdate_range("2010-01-01", periods=dates), stocks),
    "symbol": np.tile([f"S{i}" for i in range(stocks)], dates),
    "f": factor, "r": .2 * control + (.05 + .2 * (moderator > 50)) * factor + rng.normal(size=n),
    "log_cap": control, "volatility": rng.uniform(.01, .2, n),
    "log_turnover": rng.normal(size=n),
    "industry": np.tile([f"I{i%5}" for i in range(stocks)], dates),
    "moderator": moderator})
cuts = {"median": {"field": "moderator", "value": 50, "side": "high"}}
from time import perf_counter
start=perf_counter()
forest = forest_propose(frame, ["moderator"], cuts, ResearchConfig(workers=1))
one_seconds=perf_counter()-start
start=perf_counter()
parallel = forest_propose(frame, ["moderator"], cuts, ResearchConfig(workers=8))
parallel_seconds=perf_counter()-start
assert forest == parallel, "Worker count changed frozen forest output"
icm = blade_icm(frame, "moderator", 50, 5, ResearchConfig())
result = {"worker_count_deterministic": True, "one_seconds": one_seconds, "parallel_seconds":parallel_seconds, "forest": {k:v for k,v in forest.items() if k != "internal_leaf_effects"},
          "icm": icm,
          "scope": "Strong synthetic interaction runtime; not calibrated discovery recovery or real factor evidence"}
Path("artifacts/validation/discovery-runtime.json").write_text(json.dumps(result, indent=2))
print(result, flush=True)
if not forest.get("valid_trees") or icm["p"] >= .05:
    raise SystemExit("Synthetic interaction runtime failed")
