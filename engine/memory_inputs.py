"""Joint quarterly measurement covariance for shared-date research structures."""
from pathlib import Path

import numpy as np
import pandas as pd


def build_memory_inputs(rows, folder: Path, n_boot=1000, seed=42):
    # Relabeling an identical signal is not another independent observation.
    unique = {}
    for row in rows:
        if row["blades"]["placebo"]["state"] != "pass":
            continue
        if any(a["kind"] == "side" and a["state"] == "violated" for a in row["blades"]["assertions"]):
            continue
        unique[row["fingerprint"]] = row
    eligible = list(unique.values())
    records, daily = [], {}
    for row in eligible:
        h = row["structure"]["primary_horizon"]
        values = pd.read_parquet(folder / row["id"] / "daily-ic.parquet")
        daily[row["id"]] = values[f"ic_e1_h{h}"]
        for q in row["measurement"]["quarterly"]:
            if q["mean"] is not None and q["se"] is not None and q["se"] > 0:
                records.append({"structure": row["id"], "period": q["period"],
                                "family": row["family"], "form": str(row["form"]),
                                "mean": q["mean"], "se": q["se"]})
    frame = pd.DataFrame(records)
    if frame.empty:
        return frame, None, {"state": "no_eligible_quarters"}
    covariance = np.zeros((len(frame), len(frame)))
    rng = np.random.default_rng(seed)
    for period, group in frame.groupby("period", sort=True):
        series = pd.concat({sid:daily[sid] for sid in group.structure}, axis=1)
        series = series[series.index.to_period("Q").astype(str) == period]
        values = series.to_numpy()
        block = 20
        if len(values) < 2*block:
            return frame, None, {"state": "insufficient_joint_date_blocks", "period": period}
        starts = rng.integers(0,len(values)-block+1,size=(n_boot,int(np.ceil(len(values)/block))))
        indices = (starts[...,None]+np.arange(block)).reshape(n_boot,-1)[:,:len(values)]
        sampled = values[indices]
        count = np.isfinite(sampled).sum(axis=1)
        means = np.divide(np.nansum(sampled,axis=1),count,
                          out=np.full(count.shape,np.nan),where=count>0)
        means = means[np.isfinite(means).all(axis=1)]
        if len(means) < .95*n_boot or np.any(means.std(axis=0) <= 1e-12):
            return frame, None, {"state": "unidentified_joint_covariance", "period": period}
        corr = np.atleast_2d(np.corrcoef(means,rowvar=False))
        # Keep each structure's conservative finite-block marginal standard error.
        errors = group.se.to_numpy()
        matrix = corr * np.outer(errors,errors)
        eig,vec = np.linalg.eigh(matrix)
        floor = max(float(np.diag(matrix).max())*1e-8,1e-14)
        matrix = (vec*np.maximum(eig,floor))@vec.T
        positions = group.index.to_numpy()
        covariance[np.ix_(positions,positions)] = matrix
    return frame,covariance,{"state":"estimated","method":"joint date-block bootstrap correlation with conservative marginal SE",
        "blocks":20,"replicates":n_boot,"unique_signals":len(eligible),"quarter_rows":len(frame),
        "between_quarter_covariance":"not estimated; quarter boundary dependence remains a limitation"}
