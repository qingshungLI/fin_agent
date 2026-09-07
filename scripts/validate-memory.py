"""Synthetic runtime check of the Bayesian memory; no market observations."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from engine.memory import fit_hierarchy

rng = np.random.default_rng(731)
rows = []
for structure in range(4):
    for quarter in range(12):
        rows.append({"structure": str(structure), "family": "M" + str(structure // 2 + 1),
                     "form": str(structure % 2 + 1), "period": str(quarter),
                     "mean": float(.01 + .003 * structure + rng.normal(0, .004)),
                     "se": .004})
result = fit_hierarchy(pd.DataFrame(rows), seed=731)
result["scope"] = "Synthetic four-structure runtime and convergence check only; no recovery certification"
Path("artifacts/validation/memory-runtime.json").write_text(json.dumps(result, indent=2))
print({k: v for k, v in result.items() if k != "terms"}, flush=True)
