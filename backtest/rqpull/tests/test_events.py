import pandas as pd

from rqpull.tasks.events import _wide_flag_to_long


def test_wide_flag_to_long():
    frame = pd.DataFrame(
        {"000001.XSHE": [False, True], "600000.XSHG": [False, False]},
        index=pd.Index(pd.to_datetime(["2020-01-02", "2020-01-03"]), name="date"),
    )
    result = _wide_flag_to_long(frame, "is_st")
    assert set(result.columns) == {"date", "order_book_id", "is_st"}
    assert len(result) == 4
