# 回测框架使用说明

本目录把原 `原项目` 的回测链路迁移到 `.`，直接使用
`./data` 中的 Parquet 数据，不复制数据文件。

## 目录

- `backtest/rqalpha_mod_local_rqdata/`：RQAlpha 本地数据源 Mod。
- `backtest/rqpull/`：数据仓库和 DuckDB 视图构建代码。
- `backtest/rqalpha_minimal_backtest.py`：RQAlpha 最小回测入口。
- `backtest/rqalpha_smoke.py`：环境和数据目录检查。
- `backtest/build_warehouse.py`：从 Parquet 创建 `data/warehouse.duckdb`。
- `backtest/industry_rotation_model.py`：行业轮动研究型回测脚本。

## 环境准备

建议使用目标项目自己的虚拟环境；如果尚未创建：

```powershell
cd .
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -U pip
.venv\Scripts\python.exe -m pip install pandas pyarrow duckdb numpy scipy rqalpha lightgbm
```

RQAlpha 不是数据下载器。正式回测前需要安装本地 Mod：

```powershell
cd .
$env:PYTHONPATH = "./backtest"
.venv\Scripts\python.exe -m pip install -e .\backtest\rqalpha_mod_local_rqdata
```

如果目标项目没有 `pyproject.toml`，只执行上面的 `PYTHONPATH` 设置即可。

## 首次初始化

先检查数据，再生成 DuckDB 视图：

```powershell
cd .
$env:PYTHONPATH = "./backtest"
.venv\Scripts\python.exe .\backtest\rqalpha_smoke.py
.venv\Scripts\python.exe .\backtest\build_warehouse.py
```

默认路径如下：

```text
数据根目录: ./data
DuckDB:    ./data\warehouse.duckdb
```

可通过环境变量切换数据集或仓库位置：

```powershell
$env:FINANCE_DATA_ROOT = "./data"
$env:FINANCE_WAREHOUSE_PATH = "./data\warehouse.duckdb"
```

数据目录至少应包含：`daily_bar`、`trading_calendar.parquet`、`instruments.parquet`、
`return_calibration`、`dividend`、`split`、`suspension`、`st_flag`、`open_auction`、
`yield_curve.parquet`。行业轮动还需要 `industry_citics_level3` 或对应行业面板。

## 运行最小 RQAlpha 回测

```powershell
cd .
$env:PYTHONPATH = "./backtest"
.venv\Scripts\python.exe .\backtest\rqalpha_minimal_backtest.py
```

该脚本只验证 RQAlpha 生命周期和本地数据接入，当前 `handle_bar` 为空，不代表任何投资策略。
要运行真实策略，应在策略文件中实现 `init`、`before_trading`、`handle_bar`，并通过
`rqalpha.run_func` 传入配置。A 股交易规则、复权、停牌和公司行为由本地 DataSource 提供。

## 运行行业轮动研究回测

该脚本是 pandas 研究引擎，不依赖 RQAlpha 撮合器。它读取 `panel_sw2*.parquet` 和
`panel_sw3*.parquet`，执行固定参数的 purged walk-forward 评估：

```powershell
cd .
.venv\Scripts\python.exe .\backtest\industry_rotation_model.py --exact --fwd 10
```

注意：迁移脚本默认寻找目标目录根下的 `panel_sw2_exact.parquet`、`panel_sw3_exact.parquet`。
若目标数据只有股票级 Parquet，需要先生成行业面板，或在脚本中把输入路径改为已生成的面板文件。

## 输出与排错

- RQAlpha 分析结果：由 `sys_analyser` 返回；可进一步配置 `report_save_path` 保存报告。
- DuckDB 视图：`data/warehouse.duckdb` 中以 `v_` 开头，例如 `v_daily_bar`、`v_instruments`。
- `No module named rqalpha`：在目标 `.venv` 安装 `rqalpha`，不要使用系统 Python。
- `No module named rqalpha_mod_local_rqdata`：设置 `PYTHONPATH` 或重新执行本地 Mod 安装。
- 找不到数据：检查 `FINANCE_DATA_ROOT`，以及 Parquet 分区是否存在。
- 回测结果为空：先确认日期落在交易日历内，并检查对应年份的 `daily_bar` 分区。

## 数据与结果边界

回测只能使用当时可获得的数据。行业分类应使用 point-in-time 快照，未来收益标签只能用于
评估，不能进入当日特征。参数搜索不得混入锁定的样本外区间；每次运行应记录代码版本、数据
根目录、回测区间、费用参数和输出文件路径。
