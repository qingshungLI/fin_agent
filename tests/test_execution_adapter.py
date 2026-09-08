from types import SimpleNamespace
import pandas as pd
import pytest

LocalRQDataSource = pytest.importorskip(
    "rqalpha_mod_local_rqdata.data_source",
    reason="RQAlpha local backtest adapter is optional; install project backtest extras to run adapter tests",
).LocalRQDataSource


def test_missing_suspension_is_not_silently_tradable():
    source = LocalRQDataSource.__new__(LocalRQDataSource)
    source.store = SimpleNamespace(status=lambda *args: {})
    with pytest.raises(ValueError, match="Missing historical"):
        source.is_suspended("A", [pd.Timestamp("2018-01-02")])


def test_explicit_status_is_preserved():
    source = LocalRQDataSource.__new__(LocalRQDataSource)
    source.store = SimpleNamespace(status=lambda *args: {20180102: True, 20180103: False})
    assert source.is_suspended("A", [pd.Timestamp("2018-01-02"), pd.Timestamp("2018-01-03")]) == [True,False]
