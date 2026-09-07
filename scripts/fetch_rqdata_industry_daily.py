"""Bounded, resumable A-only direct daily industry queries from RQData."""
import contextlib
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import rqdatac as rq

from engine.audit import digest, write_json
from engine.cache import file_hash
from engine.pipeline import project_lock

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "artifacts/vendor-setup/industry-daily-A-20260907"
TARGET = ROOT / "data/industry_sws_daily"


def main():
    with project_lock(ROOT/"artifacts"):
        fetch()


def fetch():
    if rq.__version__ != "3.5.6.1":
        raise ValueError("Pinned RQData client required")
    values = dict(x.split("=",1) for x in (ROOT/".env").read_text().splitlines()
                  if "=" in x and not x.lstrip().startswith("#"))
    symbols = sorted(pq.read_table(ROOT/"data/instruments.parquet").to_pandas().order_book_id.tolist())
    calendar = pd.to_datetime(pq.read_table(ROOT/"data/trading_calendar.parquet").to_pandas().date)
    dates = calendar[(calendar >= "2016-07-01") & (calendar <= "2022-06-30")].dt.strftime("%Y-%m-%d").tolist()
    identity = {"symbols":symbols,"dates":dates,"provider":"RQData","source":"sws",
                "client_version":rq.__version__,"api":"get_instrument_industry","level":0}
    CACHE.mkdir(parents=True,exist_ok=True)
    identity_path = CACHE/"identity.json"
    if identity_path.exists() and json.loads(identity_path.read_text()) != identity:
        raise ValueError("Download identity changed")
    write_json(identity_path,identity)
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
        rq.init("license",values["RQDATAC_LICENSE"],connect_timeout=10,timeout=40,auto_load_plugins=False)
    quota_start = rq.user.get_quota()["bytes_used"]

    def one(date):
        path = CACHE/(date+".parquet")
        receipt = CACHE/(date+".json")
        if path.exists() and receipt.exists():
            record=json.loads(receipt.read_text())
            if record["sha256"] != file_hash(path) or record["identity_hash"] != digest(identity):
                raise ValueError("Corrupt daily download")
            return date,True
        for attempt in range(3):
            try:
                frame=rq.get_instrument_industry(symbols,source="sws",level=0,date=date)
                if frame is None or frame.empty:
                    raise ValueError("Empty daily industry response")
                frame=frame.reset_index()
                if frame.order_book_id.duplicated().any() or not set(frame.order_book_id)<=set(symbols):
                    raise ValueError("Invalid daily response keys")
                frame["date"]=pd.Timestamp(date)
                frame["retrieved_at"]=pd.Timestamp.now(tz="UTC")
                temporary=path.with_suffix(".tmp")
                frame.to_parquet(temporary,index=False)
                temporary.replace(path)
                write_json(receipt,{"date":date,"identity_hash":digest(identity),
                    "rows":len(frame),"sha256":file_hash(path),"retrieved_at":datetime.now(UTC).isoformat()})
                return date,False
            except Exception:
                if attempt==2: raise
                time.sleep(2**attempt)

    done=0
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures={pool.submit(one,date):date for date in dates}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    for pending in futures:
                        pending.cancel()
                    raise
                done+=1
                if done%100==0 or done==len(dates):
                    write_json(CACHE/"progress.json",{"status":"FETCHING","completed":done,"total":len(dates)})
                    print(f"industry dates {done}/{len(dates)}",flush=True)
                    quota=rq.user.get_quota()
                    if quota["bytes_used"]-quota_start > 2_000_000_000:
                        for pending in futures: pending.cancel()
                        raise RuntimeError("Metadata download budget reached")
        if TARGET.exists():
            raise ValueError("Candidate dataset already exists; never overwrite source data")
        temporary=ROOT/"data/.industry_sws_daily.building"
        temporary.mkdir(parents=True,exist_ok=False)
        for year in sorted({date[:4] for date in dates}):
            frames=[pd.read_parquet(CACHE/(date+".parquet")) for date in dates if date.startswith(year)]
            frame=pd.concat(frames,ignore_index=True)
            frame=frame[["order_book_id","date","third_industry_code","first_industry_code",
                         "second_industry_code","retrieved_at"]].copy()
            if frame.duplicated(["order_book_id","date"]).any() or frame.third_industry_code.isna().any():
                raise ValueError("Invalid candidate daily industry panel")
            frame["source"]="sws"
            frame["client_version"]=rq.__version__
            path=temporary/("year="+year)/"data.parquet"
            path.parent.mkdir(parents=True)
            frame.to_parquet(path,index=False)
        write_json(temporary/"manifest.json",{"identity":identity,"status":"DIRECT_DAILY_QUERIES",
            "return_data_read":False,"forward_or_backfill":False,
            "warning":"Current vendor response for historical effective dates; not archived historical publication vintages",
            "files":{str(p.relative_to(temporary)):file_hash(p) for p in temporary.rglob("*.parquet")}})
        temporary.rename(TARGET)
        write_json(CACHE/"progress.json",{"status":"COMPLETED","completed":done,"total":len(dates),
                                          "target":str(TARGET),"bytes_used_delta":rq.user.get_quota()["bytes_used"]-quota_start})
        print("Daily industry candidate published; raw interval files unchanged",flush=True)
    except Exception as exc:  # noqa: BLE001 - checkpoint failure without exposing credentials
        write_json(CACHE/"progress.json",{"status":"FAILED","completed":done,"total":len(dates),"error_type":type(exc).__name__})
        print("Industry download failed: "+type(exc).__name__,flush=True)
        raise SystemExit(2)


if __name__=="__main__":
    main()
