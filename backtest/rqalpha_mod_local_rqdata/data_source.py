from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Union

import numpy as np
import pandas as pd
import six

from rqalpha.const import INSTRUMENT_TYPE, MARKET, TRADING_CALENDAR_TYPE
from rqalpha.data.base_data_source.adjust import FIELDS_REQUIRE_ADJUSTMENT, adjust_bars
from rqalpha.interface import AbstractDataSource, ExchangeRate
from rqalpha.model.instrument import Instrument
from rqalpha.utils.datetime_func import convert_date_to_int
from rqalpha.utils.exception import RQInvalidArgument

from .stores import WarehouseStore, date_key


class LocalRQDataSource(AbstractDataSource):
    exchange_rate_1 = ExchangeRate(1, 1, 1, 1, 1, 1)

    def __init__(self, warehouse_path: Union[str, Path]):
        self.store = WarehouseStore(Path(warehouse_path))

    def close(self):
        self.store.close()

    def get_instruments(
        self,
        id_or_syms: Optional[Iterable[str]] = None,
        types: Optional[Iterable[INSTRUMENT_TYPE]] = None,
    ) -> Iterable[Instrument]:
        if id_or_syms is not None:
            seen = set()
            for value in id_or_syms:
                candidates = []
                by_id = self.store.instruments_by_id.get(value)
                if by_id is not None:
                    candidates.append(by_id)
                candidates.extend(self.store.instruments_by_symbol.get(value, []))
                for instrument in candidates:
                    if instrument not in seen:
                        seen.add(instrument)
                        yield instrument
            return
        requested = set(types) if types is not None else {INSTRUMENT_TYPE.CS}
        if INSTRUMENT_TYPE.CS in requested:
            yield from self.store.instruments

    def get_trading_calendars(self):
        return {TRADING_CALENDAR_TYPE.CN_STOCK: self.store.trading_calendar}

    def available_data_range(self, frequency):
        if frequency not in {"1d", "tick"}:
            raise NotImplementedError("local RQData source only supports A-share daily bars")
        return self.store.data_range

    def get_bar(self, instrument, dt, frequency):
        if frequency != "1d":
            raise NotImplementedError("local RQData source only supports A-share daily bars")
        bars = self.store.bars(instrument.order_book_id)
        if len(bars) == 0:
            return None
        dt_int = np.uint64(convert_date_to_int(dt))
        position = bars["datetime"].searchsorted(dt_int)
        if position >= len(bars) or bars["datetime"][position] != dt_int:
            return None
        return bars[position]

    @staticmethod
    def _fields_valid(fields, valid_fields):
        if fields is None:
            return True
        if isinstance(fields, six.string_types):
            return fields in valid_fields
        return all(field in valid_fields for field in fields)

    def history_bars(
        self,
        instrument: Instrument,
        bar_count: Optional[int],
        frequency: str,
        fields: Union[str, List[str], None],
        dt: datetime,
        skip_suspended: bool = True,
        include_now: bool = False,
        adjust_type: str = "pre",
        adjust_orig: Optional[datetime] = None,
    ) -> Optional[np.ndarray]:
        if frequency != "1d":
            raise NotImplementedError("local RQData source only supports A-share daily bars")
        if adjust_type not in {"none", "pre", "post"}:
            raise RQInvalidArgument(f"invalid adjust_type: {adjust_type}")

        bars = self.store.bars(instrument.order_book_id)
        if not self._fields_valid(fields, bars.dtype.names):
            raise RQInvalidArgument(f"invalid fields: {fields}")
        if skip_suspended and len(bars):
            suspended = self.store.status(
                "v_suspension", "is_suspended", instrument.order_book_id
            )
            keep = np.fromiter(
                (not suspended[int(value // 1_000_000)] for value in bars["datetime"]),
                dtype=bool,
                count=len(bars),
            )
            bars = bars[keep]

        right = bars["datetime"].searchsorted(
            np.uint64(convert_date_to_int(dt)), side="right"
        )
        left = 0 if bar_count is None else max(0, right - bar_count)
        bars = bars[left:right]
        if adjust_type != "none" and not (
            isinstance(fields, str) and fields not in FIELDS_REQUIRE_ADJUSTMENT
        ):
            bars = adjust_bars(
                bars,
                self.store.factors(instrument.order_book_id),
                fields,
                adjust_type,
                adjust_orig or dt,
            )
        return bars if fields is None else bars[fields]

    def _checked_status(self, view, field, order_book_id, dates):
        values = self.store.status(view, field, order_book_id)
        result = []
        for day in dates:
            key = date_key(day)
            if key not in values:
                raise ValueError(f"Missing historical {field}: {order_book_id} {key}")
            result.append(values[key])
        return result

    def is_suspended(self, order_book_id: str, dates: Sequence) -> List[bool]:
        return self._checked_status("v_suspension", "is_suspended", order_book_id, dates)

    def is_st_stock(self, order_book_id: str, dates: Sequence) -> List[bool]:
        return self._checked_status("v_st_flag", "is_st", order_book_id, dates)

    def get_dividend(self, instrument):
        return self.store.dividends(instrument.order_book_id)

    def get_split(self, instrument):
        return self.store.splits(instrument.order_book_id)

    def get_open_auction_bar(self, instrument, dt):
        bar = self.store.auctions(instrument.order_book_id).get(date_key(dt))
        if bar is not None:
            return bar
        return {
            "datetime": int(convert_date_to_int(dt)),
            "open": np.nan,
            "last": np.nan,
            "limit_up": np.nan,
            "limit_down": np.nan,
            "volume": np.nan,
            "total_turnover": np.nan,
            "prev_close": np.nan,
        }

    def get_open_auction_volume(self, instrument, dt):
        return self.get_open_auction_bar(instrument, dt)["volume"]

    def get_yield_curve(self, start_date, end_date, tenor=None):
        fields = ["date"]
        if tenor:
            fields.extend(tenor)
        else:
            fields.extend(
                row[1]
                for row in self.store.connection.execute(
                    "PRAGMA table_info('v_yield_curve')"
                ).fetchall()
                if row[1] != "date"
            )
        quoted = ", ".join(f'"{field}"' for field in fields)
        frame = self.store.connection.execute(
            f"SELECT {quoted} FROM v_yield_curve WHERE date BETWEEN ? AND ? ORDER BY date",
            [pd.Timestamp(start_date), pd.Timestamp(end_date)],
        ).fetchdf()
        if frame.empty:
            return frame.set_index("date")
        return frame.set_index("date")

    def get_share_transformation(self, order_book_id):
        return None

    def get_exchange_rate(
        self, trading_date: date, local: MARKET, settlement: MARKET = MARKET.CN
    ) -> ExchangeRate:
        if local == settlement:
            return self.exchange_rate_1
        raise NotImplementedError("local RQData source only supports the CNY market")

    def get_settle_price(self, instrument, date):
        return np.nan

    def current_snapshot(self, instrument, frequency, dt):
        raise NotImplementedError("local RQData source only supports A-share daily bars")

    def history_ticks(self, instrument, count, dt):
        raise NotImplementedError("local RQData source only supports A-share daily bars")

    def get_trading_minutes_for(self, instrument, trading_dt):
        raise NotImplementedError("local RQData source only supports A-share daily bars")

    def get_futures_trading_parameters(self, instrument, dt):
        raise NotImplementedError("local RQData source does not support futures")

    def get_merge_ticks(self, order_book_id_list, trading_date, last_dt=None):
        raise NotImplementedError("local RQData source does not support ticks")

    def get_algo_bar(self, id_or_ins, start_min, end_min, dt):
        raise NotImplementedError("local RQData source does not support algorithmic orders")
