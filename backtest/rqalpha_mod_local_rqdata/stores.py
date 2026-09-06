from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from rqalpha.model.instrument import Instrument
from rqalpha.utils.datetime_func import convert_date_to_int


DAY_BAR_DTYPE = np.dtype(
    [
        ("datetime", np.uint64),
        ("open", np.float64),
        ("close", np.float64),
        ("high", np.float64),
        ("low", np.float64),
        ("volume", np.float64),
        ("total_turnover", np.float64),
        ("limit_up", np.float64),
        ("limit_down", np.float64),
        ("prev_close", np.float64),
        ("num_trades", np.float64),
    ]
)

EX_FACTOR_DTYPE = np.dtype(
    [("start_date", np.uint64), ("ex_cum_factor", np.float64)]
)

DIVIDEND_DTYPE = np.dtype(
    [
        ("book_closure_date", np.int64),
        ("announcement_date", np.int64),
        ("dividend_cash_before_tax", np.float64),
        ("ex_dividend_date", np.int64),
        ("payable_date", np.int64),
        ("round_lot", np.float64),
    ]
)

SPLIT_DTYPE = np.dtype(
    [("ex_date", np.int64), ("split_factor", np.float64)]
)


def date_key(value) -> int:
    if isinstance(value, (int, np.integer)):
        value = int(value)
        return value // 1_000_000 if value >= 1_000_000_000_000 else value
    return pd.Timestamp(value).year * 10000 + pd.Timestamp(value).month * 100 + pd.Timestamp(value).day


def date_time_int(value) -> int:
    return int(convert_date_to_int(pd.Timestamp(value)))


def nullable_date_key(value) -> int:
    return 0 if pd.isna(value) else date_key(value)


class WarehouseStore:
    def __init__(self, warehouse_path: Path):
        self.path = warehouse_path.resolve()
        if not self.path.is_file():
            raise RuntimeError(f"local RQData warehouse does not exist: {self.path}")
        self.connection = duckdb.connect(str(self.path), read_only=True)
        self._bars: dict[str, np.ndarray] = {}
        self._status: dict[tuple[str, str], dict[int, bool]] = {}
        self._factors: dict[str, np.ndarray | None] = {}
        self._dividends: dict[str, np.ndarray | None] = {}
        self._splits: dict[str, np.ndarray | None] = {}
        self._auctions: dict[str, dict[int, dict]] = {}

        self.instruments = self._load_instruments()
        self.instruments_by_id = {i.order_book_id: i for i in self.instruments}
        self.instruments_by_symbol: dict[str, list[Instrument]] = {}
        for instrument in self.instruments:
            self.instruments_by_symbol.setdefault(instrument.symbol, []).append(instrument)

        calendar = self.connection.execute(
            "SELECT date FROM v_trading_calendar ORDER BY date"
        ).fetchdf()
        self.trading_calendar = pd.DatetimeIndex(calendar["date"]).drop_duplicates()
        minimum, maximum = self.connection.execute(
            "SELECT min(date), max(date) FROM v_daily_bar"
        ).fetchone()
        self.data_range = (pd.Timestamp(minimum).date(), pd.Timestamp(maximum).date())

    def close(self):
        self.connection.close()

    def _load_instruments(self) -> list[Instrument]:
        frame = self.connection.execute(
            "SELECT * FROM v_instruments WHERE type = 'CS' ORDER BY order_book_id, listed_date"
        ).fetchdf()
        instruments = []
        for record in frame.to_dict("records"):
            clean = {}
            for key, value in record.items():
                if pd.isna(value):
                    continue
                if isinstance(value, pd.Timestamp):
                    clean[key] = value.strftime("%Y-%m-%d")
                elif isinstance(value, np.generic):
                    clean[key] = value.item()
                else:
                    clean[key] = value
            clean.setdefault(
                "listed_date", Instrument.DEFAULT_LISTED_DATE.strftime("%Y-%m-%d")
            )
            clean.setdefault(
                "de_listed_date", Instrument.DEFAULT_DE_LISTED_DATE.strftime("%Y-%m-%d")
            )
            instruments.append(Instrument(clean))
        return instruments

    def bars(self, order_book_id: str) -> np.ndarray:
        cached = self._bars.get(order_book_id)
        if cached is not None:
            return cached
        frame = self.connection.execute(
            """
            SELECT date, open, close, high, low, volume, total_turnover,
                   limit_up, limit_down, prev_close, num_trades
            FROM v_daily_bar
            WHERE order_book_id = ?
            ORDER BY date
            """,
            [order_book_id],
        ).fetchdf()
        result = np.empty(len(frame), dtype=DAY_BAR_DTYPE)
        if len(frame):
            result["datetime"] = np.asarray(
                [date_time_int(value) for value in frame["date"]], dtype=np.uint64
            )
            for field in DAY_BAR_DTYPE.names[1:]:
                result[field] = frame[field].to_numpy(dtype=np.float64, na_value=np.nan)
        self._bars[order_book_id] = result
        return result

    def status(self, view: str, field: str, order_book_id: str) -> dict[int, bool]:
        cache_key = (view, order_book_id)
        cached = self._status.get(cache_key)
        if cached is not None:
            return cached
        rows = self.connection.execute(
            f'SELECT date, "{field}" FROM "{view}" WHERE order_book_id = ? ORDER BY date',
            [order_book_id],
        ).fetchall()
        result = {date_key(row[0]): bool(row[1]) for row in rows}
        self._status[cache_key] = result
        return result

    def factors(self, order_book_id: str) -> np.ndarray | None:
        if order_book_id in self._factors:
            return self._factors[order_book_id]
        rows = self.connection.execute(
            """
            SELECT ex_date, ex_cum_factor
            FROM v_adj_factor
            WHERE order_book_id = ? AND ex_cum_factor IS NOT NULL
            ORDER BY ex_date
            """,
            [order_book_id],
        ).fetchall()
        if not rows:
            self._factors[order_book_id] = None
            return None
        result = np.empty(len(rows) + 1, dtype=EX_FACTOR_DTYPE)
        result[0] = (0, 1.0)
        for index, (event_date, factor) in enumerate(rows, start=1):
            result[index] = (date_time_int(event_date), float(factor))
        self._factors[order_book_id] = result
        return result

    def dividends(self, order_book_id: str) -> np.ndarray | None:
        if order_book_id in self._dividends:
            return self._dividends[order_book_id]
        rows = self.connection.execute(
            """
            SELECT book_closure_date, declaration_announcement_date,
                   dividend_cash_before_tax, ex_dividend_date, payable_date, round_lot
            FROM v_dividend
            WHERE order_book_id = ? AND ex_dividend_date IS NOT NULL
            ORDER BY ex_dividend_date
            """,
            [order_book_id],
        ).fetchall()
        if not rows:
            self._dividends[order_book_id] = None
            return None
        result = np.empty(len(rows), dtype=DIVIDEND_DTYPE)
        for index, row in enumerate(rows):
            result[index] = (
                nullable_date_key(row[0]),
                nullable_date_key(row[1]),
                float(row[2]),
                date_key(row[3]),
                nullable_date_key(row[4]),
                float(row[5]),
            )
        self._dividends[order_book_id] = result
        return result

    def splits(self, order_book_id: str) -> np.ndarray | None:
        if order_book_id in self._splits:
            return self._splits[order_book_id]
        rows = self.connection.execute(
            """
            SELECT ex_dividend_date, split_coefficient_to, split_coefficient_from
            FROM v_split
            WHERE order_book_id = ? AND ex_dividend_date IS NOT NULL
            ORDER BY ex_dividend_date
            """,
            [order_book_id],
        ).fetchall()
        if not rows:
            self._splits[order_book_id] = None
            return None
        result = np.empty(len(rows), dtype=SPLIT_DTYPE)
        for index, (event_date, coefficient_to, coefficient_from) in enumerate(rows):
            factor = float(coefficient_to) / float(coefficient_from)
            if not np.isfinite(factor) or factor <= 0:
                raise RuntimeError(f"invalid split factor for {order_book_id} at {event_date}")
            result[index] = (date_time_int(event_date), factor)
        self._splits[order_book_id] = result
        return result

    def auctions(self, order_book_id: str) -> dict[int, dict]:
        cached = self._auctions.get(order_book_id)
        if cached is not None:
            return cached
        rows = self.connection.execute(
            """
            SELECT datetime, open, last, limit_up, limit_down, volume,
                   total_turnover, prev_close
            FROM v_open_auction
            WHERE order_book_id = ?
            ORDER BY datetime
            """,
            [order_book_id],
        ).fetchall()
        result = {}
        for dt, open_, last, limit_up, limit_down, volume, turnover, prev_close in rows:
            result[date_key(dt)] = {
                "datetime": date_time_int(dt),
                "open": float(open_),
                "last": float(last),
                "limit_up": float(limit_up),
                "limit_down": float(limit_down),
                "volume": float(volume),
                "total_turnover": float(turnover),
                "prev_close": float(prev_close),
            }
        self._auctions[order_book_id] = result
        return result
