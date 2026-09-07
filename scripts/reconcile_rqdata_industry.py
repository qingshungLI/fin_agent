"""Query only industry metadata for prior counterexamples; preserve raw sources."""
import contextlib
import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import rqdatac as rq

ROOT = Path(__file__).resolve().parents[1]


def main():
    values = dict(x.split("=",1) for x in (ROOT/".env").read_text().splitlines()
                  if "=" in x and not x.lstrip().startswith("#"))
    license_value = values["RQDATAC_LICENSE"]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT/"artifacts/validation"/("rqdata-industry-"+stamp)
    out.mkdir(parents=True,exist_ok=False)
    report = {"created_at":stamp,"client_version":rq.__version__,"source":"sws",
              "scope":"Industry metadata only; no price/return/holdout reads","queries":[],
              "original_data_modified":False}
    symbols = ["000006.XSHE","000007.XSHE","000010.XSHE","000022.XSHE",
               "000034.XSHE","000038.XSHE","000789.XSHE","002163.XSHE"]
    dates = ["2016-07-29","2017-06-30","2021-06-30","2021-07-30","2022-06-30"]
    codes = ["850611.INDX","850612.INDX","850614.INDX","857111.INDX","857121.INDX",
             "851811.INDX","850222.INDX","851711.INDX","857251.INDX","852226.INDX"]
    def save():
        (out/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str))
    try:
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            rq.init("license",license_value,connect_timeout=10,timeout=30,auto_load_plugins=False)
        report["authenticated"]=True
        for date in dates:
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                frame=rq.get_instrument_industry(symbols,source="sws",level=0,date=date)
            if frame is None: frame=pd.DataFrame()
            filename="snapshot-"+date+".parquet"
            frame.to_parquet(out/filename)
            previous=ROOT/"data/industry_sws_2021_hierarchy"/("snapshot="+date)/"data.parquet"
            differences=[]
            if previous.exists() and not frame.empty:
                local=pq.read_table(previous).to_pandas().set_index("order_book_id")
                for symbol,row in frame.iterrows():
                    old=local.loc[symbol,"third_industry_code"] if symbol in local.index else None
                    if old != row.third_industry_code:
                        differences.append({"symbol":symbol,"local":old,"online":row.third_industry_code})
            report["queries"].append({"api":"get_instrument_industry","date":date,"rows":len(frame),
                                      "differences":differences,"file":filename,
                                      "sha256":hashlib.sha256((out/filename).read_bytes()).hexdigest()})
            save()
        for code in codes:
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                frame=rq.get_industry_change(code,source="sws",level=3)
            if frame is None: frame=pd.DataFrame(columns=["order_book_id","start_date","cancel_date"])
            else: frame=frame.reset_index()
            filename="changes-"+code+".parquet"
            frame.to_parquet(out/filename,index=False)
            local=pq.read_table(ROOT/"data/industry_sws_2021_exact_changes"/("industry="+code)/"data.parquet").to_pandas()
            columns=["order_book_id","start_date","cancel_date"]
            def keys(value, columns=("order_book_id","start_date","cancel_date")):
                value=value[list(columns)].copy()
                for col in columns[1:]: value[col]=pd.to_datetime(value[col]).dt.strftime("%Y-%m-%d")
                return set(value.itertuples(index=False,name=None))
            before,after=keys(local),keys(frame)
            report["queries"].append({"api":"get_industry_change","industry":code,"rows":len(frame),
                "local_rows":len(local),"removed_local_intervals":len(before-after),"added_online_intervals":len(after-before),
                "selected_stock_intervals":[dict(zip(columns,r)) for r in sorted(after) if r[0] in symbols],
                "file":filename,"sha256":hashlib.sha256((out/filename).read_bytes()).hexdigest()})
            save()
        report["status"]="COMPLETED"
    except Exception as exc:  # noqa: BLE001 - sanitize credential-bearing vendor errors
        report.update(status="FAILED",error_type=type(exc).__name__,
                      error=str(exc).replace(license_value,"[redacted]")[:600])
    save()
    print(json.dumps({"folder":str(out),**report},ensure_ascii=False,default=str))
    if report["status"]!="COMPLETED": raise SystemExit(2)


if __name__=="__main__":
    main()
