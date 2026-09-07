"""Validate all frozen real-model priors on A features, without loading outcomes."""
import json
from pathlib import Path
import pandas as pd
from engine.cache import file_hash
from engine.catalog import Structure, register_cell, check_convergent_orientation
from engine.audit import write_json
from engine.dsl import evaluate

def main():
    cache=next(p.parent for p in Path("artifacts/cache").glob("*/manifest.json")
               if json.loads(p.read_text())["identity"]["config"].get("data_profile")=="daily")
    meta=json.loads((cache/"manifest.json").read_text())
    fields={}
    for name in meta["fields"]:
        path=cache/f"fields-{name}.parquet"
        assert file_hash(path)==meta["files"][path.name]
        fields[name]=pd.read_parquet(path)
    cuts=json.loads(Path("artifacts/rqdata-daily-A-03/cuts.json").read_text())
    rows=[]
    for path in sorted(Path("artifacts/validation/form-priors").glob("prior-*.json")):
        s=Structure.model_validate(json.loads(path.read_text()))
        try:
            expressions=[register_cell(expr,fields,cuts) for expr in s.operational]
            orientation=check_convergent_orientation(s,fields,cuts)
            coverage=evaluate(s.coverage,fields,cuts)
            row={"id":s.id,"coordinate":f"{s.family}-F{s.form}","state":"registered",
                 "expressions":expressions,"orientation":orientation,
                 "covered":int(coverage.fillna(False).astype(bool).sum().sum())}
        except ValueError as exc:
            row={"id":s.id,"coordinate":f"{s.family}-F{s.form}","state":"rejected","reason":str(exc)}
        rows.append(row)
        print({k:v for k,v in row.items() if k not in {"expressions","orientation"}},flush=True)
    write_json(Path("artifacts/validation/form-registration.json"),
               {"results":rows,"outcomes_read":False,"passed":all(r["state"]=="registered" for r in rows)})
    return 0 if all(r["state"]=="registered" for r in rows) else 2

if __name__=="__main__": raise SystemExit(main())
