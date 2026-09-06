#!/usr/bin/env python3
"""Offline preflight for the local RQAlpha A-share backtest stack."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from pathlib import Path


REQUIRED_VIEWS = {
    "v_daily_bar": {
        "order_book_id",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "total_turnover",
        "limit_up",
        "limit_down",
    },
    "v_instruments": {
        "order_book_id",
        "symbol",
        "type",
        "exchange",
        "listed_date",
        "de_listed_date",
        "round_lot",
        "market_tplus",
    },
    "v_trading_calendar": {"date"},
    "v_adj_factor": {"order_book_id", "ex_date", "ex_cum_factor"},
    "v_suspension": {"order_book_id", "date", "is_suspended"},
    "v_st_flag": {"order_book_id", "date", "is_st"},
    "v_dividend": {
        "order_book_id",
        "declaration_announcement_date",
        "dividend_cash_before_tax",
        "book_closure_date",
        "ex_dividend_date",
        "payable_date",
        "round_lot",
    },
    "v_split": {
        "order_book_id",
        "ex_dividend_date",
        "split_coefficient_from",
        "split_coefficient_to",
    },
    "v_open_auction": {
        "order_book_id",
        "datetime",
        "last",
        "volume",
        "total_turnover",
        "limit_up",
        "limit_down",
    },
    "v_yield_curve": {"date"},
}

DATE_COLUMNS = {
    "v_daily_bar": "date",
    "v_trading_calendar": "date",
    "v_adj_factor": "ex_date",
    "v_suspension": "date",
    "v_st_flag": "date",
    "v_dividend": "ex_dividend_date",
    "v_split": "ex_dividend_date",
    "v_open_auction": "datetime",
    "v_yield_curve": "date",
}


def parse_args() -> argparse.Namespace:
    default_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(
        description="Check the project RQAlpha environment and local DuckDB contract."
    )
    parser.add_argument("--project-root", type=Path, default=default_root)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.project_root.expanduser().resolve()
    warehouse = root / "cache/rqdata/warehouse.duckdb"
    expected_python = root / ".venv/bin/python"
    errors: list[str] = []
    warnings: list[str] = []

    report: dict[str, object] = {
        "project_root": str(root),
        "python": sys.executable,
        "expected_python": str(expected_python),
        "warehouse": str(warehouse),
        "views": {},
    }

    if Path(sys.executable).resolve() != expected_python.resolve():
        errors.append(f"Use the project interpreter: {expected_python}")

    try:
        rqalpha_version = importlib.metadata.version("rqalpha")
        report["rqalpha_version"] = rqalpha_version
        if rqalpha_version != "6.3.0":
            warnings.append(
                f"Skill was researched against RQAlpha 6.3.0; found {rqalpha_version}. "
                "Re-check interface.py before implementing the adapter."
            )
    except importlib.metadata.PackageNotFoundError:
        errors.append("RQAlpha is not installed in the project virtual environment")

    try:
        import rqalpha_mod_local_rqdata

        report["local_mod"] = str(Path(rqalpha_mod_local_rqdata.__file__).resolve())
    except ImportError:
        errors.append(
            "rqalpha_mod_local_rqdata is not importable; run scripts/install_local_mod.py"
        )

    try:
        import duckdb

        report["duckdb_version"] = duckdb.__version__
    except ImportError:
        errors.append("duckdb is not installed in the project virtual environment")
        return emit(report, errors, warnings, args.as_json)

    if not warehouse.is_file():
        errors.append(f"Warehouse does not exist: {warehouse}")
        return emit(report, errors, warnings, args.as_json)

    connection = duckdb.connect(str(warehouse), read_only=True)
    try:
        available = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        for view, required_columns in REQUIRED_VIEWS.items():
            if view not in available:
                errors.append(f"Missing required view: {view}")
                continue

            columns = {
                row[1]
                for row in connection.execute(f"PRAGMA table_info('{view}')").fetchall()
            }
            missing = sorted(required_columns - columns)
            if missing:
                errors.append(f"{view} is missing columns: {', '.join(missing)}")

            details: dict[str, object] = {"column_count": len(columns)}
            date_column = DATE_COLUMNS.get(view)
            if date_column and date_column in columns:
                minimum, maximum, rows = connection.execute(
                    f'SELECT min("{date_column}"), max("{date_column}"), count(*) FROM "{view}"'
                ).fetchone()
                details.update(
                    {
                        "rows": rows,
                        "min_date": str(minimum) if minimum is not None else None,
                        "max_date": str(maximum) if maximum is not None else None,
                    }
                )
                if rows == 0:
                    errors.append(f"Required view is empty: {view}")
            report["views"][view] = details

        instrument_count = connection.execute(
            "SELECT count(*) FROM v_instruments WHERE type = 'CS'"
        ).fetchone()[0]
        report["common_stock_instruments"] = instrument_count
        if instrument_count == 0:
            errors.append("v_instruments contains no type='CS' instruments")
    finally:
        connection.close()

    return emit(report, errors, warnings, args.as_json)


def emit(
    report: dict[str, object], errors: list[str], warnings: list[str], as_json: bool
) -> int:
    report["warnings"] = warnings
    report["errors"] = errors
    report["ok"] = not errors
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"project:  {report['project_root']}")
        print(f"python:   {report['python']}")
        print(f"rqalpha:  {report.get('rqalpha_version', 'missing')}")
        print(f"local mod:{report.get('local_mod', 'missing')}")
        print(f"duckdb:   {report.get('duckdb_version', 'missing')}")
        print(f"warehouse:{report['warehouse']}")
        for view, details in report["views"].items():
            range_text = ""
            if "rows" in details:
                range_text = (
                    f" rows={details['rows']} range={details['min_date']}..{details['max_date']}"
                )
            print(f"  {view}: columns={details['column_count']}{range_text}")
        for warning in warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print("status:   OK" if not errors else "status:   FAILED")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
