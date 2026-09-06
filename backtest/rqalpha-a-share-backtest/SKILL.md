---
name: rqalpha-a-share-backtest
description: 使用 RQAlpha 设计、实现、运行和验证基于 sentiment 项目本地 DuckDB/Parquet A 股数据仓库的回测。用于编写 RQAlpha 策略、配置日线回测、接入自定义 AbstractDataSource/Mod、映射行情与公司行动数据、处理复权/停牌/ST/涨跌停/交易成本，以及排查 bundle、数据范围、未来函数和回测结果问题。
---

# RQAlpha A 股回测

将同时包含 `.venv`、`cache` 和 `skills` 的目录作为项目根目录。固定使用 `<项目根目录>/.venv/bin/python` 和其中安装的 RQAlpha；禁止静默使用全局 Python。

## 注册并检查本地 Mod

从项目根目录运行：

```bash
.venv/bin/python skills/rqalpha-a-share-backtest/scripts/install_local_mod.py
.venv/bin/python skills/rqalpha-a-share-backtest/scripts/preflight.py
```

安装脚本在当前项目虚拟环境的 `site-packages` 中写入 `.pth` 路径注册，使 `rqalpha_mod_local_rqdata` 从任意策略目录都可导入；它可重复执行。若检查失败，先修复 RQAlpha 导入、本地 Mod、DuckDB 仓库、必需视图或日期覆盖。不得用在线 RQData 或临时下载 bundle 掩盖本地数据契约问题。

## 选择数据接入方式

- 本项目默认选择“自定义 Mod + AbstractDataSource”，直接只读 `cache/rqdata/warehouse.duckdb`。在 Mod 的 `start_up()` 中调用 `env.set_data_source(...)`；同时设置 `base.rqdatac_uri: disabled`。
- 只有明确要求兼容 RQAlpha 默认 `BaseDataSource` 时才生成 bundle。`data_bundle_path` 只能指向 RQAlpha 固定格式的 HDF5/PKL/NPY/JSON bundle，不能直接指向 Parquet 目录。
- 只是在策略中读取额外因子时，可以保留基础 DataSource，并在策略或扩展 API 中读取本地因子；但本项目连基础行情也来自本地仓库，因此首选完整替换 DataSource。

需要实现或审查数据适配器时，完整阅读 [本地 DataSource 契约](references/local-data-source-contract.md)。需要编写策略、配置回测或解释结果时，完整阅读 [RQAlpha 回测指南](references/rqalpha-backtest-guide.md)。

## 执行工作流

1. 明确回测契约：股票日线 `1d`、起止日期、预热区间、历史股票池、基准、信号产生时点、成交时点、复权口径、停牌/ST/涨跌停规则、滑点、手续费和印花税。
2. 动态检查仓库范围，确认策略日期不超过 `v_daily_bar`、`v_trading_calendar` 和依赖视图各自的最大日期。
3. 将策略生命周期拆为 `init`、`before_trading`、`open_auction`、`handle_bar`、`after_trading`。禁止在 `init` 中调用 `history_bars`；日线策略通常在 `handle_bar` 形成信号，必须明确该信号是当日收盘可得还是只能下一交易日成交。
4. 使用 `run_func` 进行可测试的程序化运行。返回值按 `run_result["sys_analyser"]` 读取 `summary, trades, portfolio, stock_positions`。输出放在 `cache/backtests/<strategy>/<run_id>/`；保留配置、代码版本、数据最大日期和结果文件。禁止覆盖不同参数的运行结果。
5. 先跑单证券短区间 smoke test，再跑停牌、涨跌停、分红和拆股事件窗口，最后才跑全市场长区间。
6. 对照 DuckDB 原始记录验证 bar、复权历史、订单、成交、持仓、现金和净值。仅“程序未报错”不算验收通过。

## 强制数据口径

- 使用 `v_daily_bar` 的不复权 OHLCV 作为撮合价格。`history_bars(adjust_type='pre'/'post')` 才根据 `v_adj_factor` 派生复权序列。
- 使用 `v_suspension` 判断停牌，不能因行情有补齐值或 `volume > 0` 就推断可交易。
- 使用 `v_st_flag` 判断历史 ST；使用 `limit_up/limit_down` 和撮合 Mod 的价格限制模拟涨跌停。
- 使用 `v_instruments.listed_date/de_listed_date` 构造历史股票池，保留退市证券，避免幸存者偏差。
- 分红和拆股必须分别接入 `get_dividend()` 与 `get_split()`；不能只调价格而忽略持仓和现金变化。
- 行业、指数成分及权重使用 `snapshot_date <= signal_date` 的最近快照。新闻和财务数据按实际可用时间连接。
- 样本外区间 `2024-01-01` 至 `2026-07-30` 已锁定，禁止用它搜索参数。

## 支持边界

首个适配版本只承诺 A 股股票日线。分钟、tick、期货、ETF/LOF、算法单和实时行情必须在扩展契约和测试后才能宣称支持；未实现接口应明确抛出 `NotImplementedError`。

当前本地 Mod 已通过两段真实引擎回测：普通交易窗口成功成交和结算；`000001.XSHE` 的 2024-06-14 除息窗口成功消费税前每 10 股 7.19 元的分红记录，持仓均价按每股 0.719 元下调。升级 RQAlpha 或仓库 schema 后必须重新执行同类 smoke test。

不要修改 `.venv/site-packages/rqalpha` 源码实现项目逻辑。把数据源做成独立的 `rqalpha_mod_<name>` 包，以便版本升级、单元测试和回滚。
