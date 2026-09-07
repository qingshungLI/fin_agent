from types import SimpleNamespace
import pandas as pd
import pytest

from rqalpha_mod_local_rqdata.data_source import LocalRQDataSource


def test_missing_suspension_is_not_silently_tradable():
    source = LocalRQDataSource.__new__(LocalRQDataSource)
    source.store = SimpleNamespace(status=lambda *args: {})
    with pytest.raises(ValueError, match="Missing historical"):
        source.is_suspended("A", [pd.Timestamp("2018-01-02")])


def test_explicit_status_is_preserved():
    source = LocalRQDataSource.__new__(LocalRQDataSource)
    source.store = SimpleNamespace(status=lambda *args: {20180102: True, 20180103: False})
    assert source.is_suspended("A", [pd.Timestamp("2018-01-02"), pd.Timestamp("2018-01-03")]) == [True,False]
