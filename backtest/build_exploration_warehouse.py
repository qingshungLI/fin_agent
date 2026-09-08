"""Build read-only Parquet views restricted to the A research segment."""
from pathlib import Path
import json
import duckdb
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
TABLES = ["daily_bar", "trading_calendar", "instruments", "adj_factor", "suspension",
          "st_flag", "dividend", "split", "open_auction", "yield_curve", "return_calibration"]


def build() -> Path:
    """Build A-only views from physical Parquet; return warehouse path, excluding AppleDouble."""
    destination = ROOT / "artifacts" / "backtest" / "exploration.duckdb"
    destination.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(destination))
    created = []
    try:
        con.execute("BEGIN TRANSACTION")
        for name in TABLES:
            base = ROOT / "data" / name
            paths = sorted(base.rglob("*.parquet")) if base.is_dir() else [base.with_suffix(".parquet")]
            paths = [p for p in paths if not p.name.startswith("._") and not any(part.startswith("year=") and int(part[5:]) > 2022
                                               for part in p.parts)]
            if not paths or not all(p.is_file() for p in paths):
                raise ValueError("Missing data source: " + name)
            fields = pq.ParquetFile(paths[0]).schema_arrow.names
            date = next((c for c in ("date", "datetime", "ex_date", "ex_dividend_date") if c in fields), None)
            sources = "[" + ",".join("'" + str(p).replace("'", "''") + "'" for p in paths) + "]"
            query = f"SELECT * FROM read_parquet({sources}, union_by_name=true)"
            if date:
                query += f" WHERE \"{date}\" < TIMESTAMP '2022-07-01'"
            con.execute(f'CREATE OR REPLACE VIEW "v_{name}" AS {query}')
            created.append({"table": name, "date_column": date, "cutoff_exclusive": "2022-07-01"})
        low, high = con.execute("SELECT min(date),max(date) FROM v_daily_bar").fetchone()
        if str(high)[:10] != "2022-06-30":
            raise ValueError("Unexpected A view date boundary")
        con.execute("COMMIT")
        print("A-only warehouse:", low, high)
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    (destination.parent / "manifest.json").write_text(json.dumps(created, indent=2))
    return destination


if __name__ == "__main__":
    build()
