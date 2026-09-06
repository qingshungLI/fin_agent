import pandas as pd

from rqpull.io import normalize_frame


def test_normalize_multiindex():
    index = pd.MultiIndex.from_tuples([("000001.XSHE", pd.Timestamp("2020-01-02"))], names=["order_book_id", "date"])
    result = normalize_frame(pd.DataFrame({"close": [10.0]}, index=index))
    assert list(result.columns) == ["order_book_id", "date", "close"]

