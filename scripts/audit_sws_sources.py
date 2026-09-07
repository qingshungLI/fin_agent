"""Read-only A-period SW source reconciliation. Never imports market returns.

Version clipping is a diagnostic counterfactual based on observed code sets,
not an authoritative dictionary and never a replacement for the source files.
"""
import hashlib
import json
from pathlib import Path
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/validation/sws-source-audit"
START = pd.Timestamp("2016-07-01")
STOP = pd.Timestamp("2022-07-01")
SWITCH = pd.Timestamp("2021-07-30")


def overlaps(changes):
    result = []
    for symbol, rows in changes.groupby("order_book_id", sort=False):
        records = list(rows.sort_values("start_date").itertuples(index=False))
        for i, a in enumerate(records):
            for b in records[i+1:]:
                if b.start_date >= a.cancel_date:
                    break
                left = max(a.start_date, b.start_date, START)
                right = min(a.cancel_date, b.cancel_date, STOP)
                if left < right and a.industry_code != b.industry_code:
                    result.append({"order_book_id": symbol, "code_a": a.industry_code,
                        "code_b": b.industry_code, "overlap_start": left, "overlap_end": right})
    return pd.DataFrame(result, columns=["order_book_id","code_a","code_b","overlap_start","overlap_end"])


def reconcile(snapshots, changes):
    keys = ["order_book_id", "snapshot_date"]
    merged = snapshots.merge(changes, on="order_book_id", how="left", validate="many_to_many")
    active = merged[(merged.start_date <= merged.snapshot_date) & (merged.snapshot_date < merged.cancel_date)]
    grouped = active.groupby(keys).industry_code.agg(lambda s: sorted(set(s)))
    result = snapshots.set_index(keys).join(grouped.rename("exact_codes")).reset_index()
    result["exact_codes"] = result.exact_codes.map(lambda v: v if isinstance(v, list) else [])
    result["active_code_count"] = result.exact_codes.map(len)
    result["snapshot_in_exact"] = [code in codes for code,codes in zip(result.third_industry_code,result.exact_codes)]
    return result


def summary(frame):
    return {"snapshot_rows":len(frame),
            "missing_exact":int(frame.active_code_count.eq(0).sum()),
            "unambiguous":int(frame.active_code_count.eq(1).sum()),
            "multiple_exact_codes":int(frame.active_code_count.gt(1).sum()),
            "snapshot_absent_from_exact":int((~frame.snapshot_in_exact).sum()),
            "unique_exact_but_different":int((frame.active_code_count.eq(1) & ~frame.snapshot_in_exact).sum())}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    exact_files = sorted((ROOT/"data/industry_sws_2021_exact_changes").glob("industry=*/data.parquet"))
    snapshot_files = [p for p in sorted((ROOT/"data/industry_sws_2021_hierarchy").glob("snapshot=*/data.parquet"))
                      if START <= pd.Timestamp(p.parent.name.split("=")[1]) < STOP]
    changes = pd.concat([pq.read_table(p).to_pandas() for p in exact_files],ignore_index=True)
    snapshots = pd.concat([pq.read_table(p).to_pandas() for p in snapshot_files],ignore_index=True)
    for field in ["start_date","cancel_date"]:
        changes[field] = pd.to_datetime(changes[field])
    snapshots.snapshot_date = pd.to_datetime(snapshots.snapshot_date)
    if snapshots.duplicated(["order_book_id","snapshot_date"]).any():
        raise ValueError("Non-unique monthly snapshots")
    if changes[["start_date","cancel_date"]].isna().any().any() or (changes.start_date >= changes.cancel_date).any():
        raise ValueError("Invalid exact intervals")
    old = set(snapshots.loc[snapshots.snapshot_date < SWITCH,"third_industry_code"].dropna())
    new = set(snapshots.loc[snapshots.snapshot_date >= SWITCH,"third_industry_code"].dropna())
    trial = changes.copy()
    trial.loc[trial.industry_code.isin(old-new),"cancel_date"] = trial.loc[trial.industry_code.isin(old-new),"cancel_date"].clip(upper=SWITCH)
    trial.loc[trial.industry_code.isin(new-old),"start_date"] = trial.loc[trial.industry_code.isin(new-old),"start_date"].clip(lower=SWITCH)
    trial = trial[trial.start_date < trial.cancel_date]
    raw_pairs, trial_pairs = overlaps(changes), overlaps(trial)
    raw, clipped = reconcile(snapshots,changes), reconcile(snapshots,trial)
    raw_pairs.to_csv(OUT/"raw-overlap-pairs.csv",index=False)
    trial_pairs.to_csv(OUT/"diagnostic-clipped-overlap-pairs.csv",index=False)
    for name,frame in [("raw",raw),("diagnostic-clipped",clipped)]:
        frame.loc[frame.active_code_count.ne(1) | ~frame.snapshot_in_exact].to_json(
            OUT/(name+"-snapshot-mismatches.json"),orient="records",date_format="iso",force_ascii=False,indent=2)
    examples = changes[changes.order_book_id.isin(["002163.XSHE","000789.XSHE"])]
    examples.to_csv(OUT/"two-stock-exact-intervals.csv",index=False)
    snapshots[snapshots.order_book_id.isin(["002163.XSHE","000789.XSHE"])].to_csv(OUT/"two-stock-snapshots.csv",index=False)
    report = {
      "scope":"A-period industry metadata only; no price/return reads; original Parquet unchanged",
      "supplier_attribution":"User supplied: RQData rqdatac==3.5.6.1, source=sws, level=3",
      "raw_files":len(exact_files),"raw_rows":len(changes),"raw_symbols":changes.order_book_id.nunique(),
      "raw_duplicate_rows":int(changes.duplicated().sum()),"monthly_snapshot_duplicate_keys":0,
      "raw_overlap_pairs_A":len(raw_pairs),"raw_overlap_symbols_A":raw_pairs.order_book_id.nunique(),
      "raw_snapshot_comparison":summary(raw),
      "diagnostic_clipping":{"switch_date":str(SWITCH.date()),"old_only_codes":len(old-new),
         "new_only_codes":len(new-old),"shared_codes":len(old&new),
         "unclassified_exact_codes":sorted(set(changes.industry_code)-(old|new)),
         "overlap_pairs_A":len(trial_pairs),"overlap_symbols_A":trial_pairs.order_book_id.nunique(),
         "snapshot_comparison":summary(clipped),"production_approved":False,
         "limitation":"Code presence/absence in monthly samples is not an official vintage dictionary; no backfill or silent production adoption"},
      "sha256":{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in exact_files+snapshot_files}}
    (OUT/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!="sha256"},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
