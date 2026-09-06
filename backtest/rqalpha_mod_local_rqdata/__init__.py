import os


__config__ = {
    "enabled": False,
    "priority": 40,
    "warehouse_path": os.environ.get(
        "FINANCE_WAREHOUSE_PATH", "data/warehouse.duckdb"
    ),
}


def load_mod():
    from .mod import LocalRQDataMod

    return LocalRQDataMod()
