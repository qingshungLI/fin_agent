from pathlib import Path

from rqalpha.interface import AbstractMod

from .data_source import LocalRQDataSource


class LocalRQDataMod(AbstractMod):
    def __init__(self):
        self._data_source = None

    def start_up(self, env, mod_config):
        warehouse_path = Path(mod_config.warehouse_path).expanduser()
        if not warehouse_path.is_absolute():
            warehouse_path = Path.cwd() / warehouse_path
        self._data_source = LocalRQDataSource(warehouse_path)
        env.set_data_source(self._data_source)

    def tear_down(self, code, exception=None):
        if self._data_source is not None:
            self._data_source.close()
