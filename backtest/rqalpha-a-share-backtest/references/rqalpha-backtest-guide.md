# RQAlpha 回测指南

## 目录

1. 本项目基线
2. RQAlpha 的运行结构
3. 最小策略
4. 推荐配置
5. 时间语义与复权
6. 交易约束和费用
7. 因子与横截面数据
8. 输出与复现实验
9. 分层验收
10. 常见错误
11. 官方资料

## 1. 本项目基线

- Python：`/Volumes/F500/sentiment/.venv/bin/python`
- RQAlpha：当前安装版本 `6.3.0`
- DuckDB：`cache/rqdata/warehouse.duckdb`
- 规范 Parquet：`cache/rqdata/std`
- 回测模式：先支持 A 股股票日线 `frequency='1d'`
- 数据源：项目内自定义 Mod 注入本地 `AbstractDataSource`
- 在线 RQData：设置 `base.rqdatac_uri='disabled'`

首次使用或项目路径变化后注册本地 Mod：

```bash
.venv/bin/python skills/rqalpha-a-share-backtest/scripts/install_local_mod.py
.venv/bin/python skills/rqalpha-a-share-backtest/scripts/preflight.py
```

每次运行都动态检查版本和数据最大日期，不能把以上版本或日期当成永久事实。

RQAlpha 官方仓库声明非商业使用与商业授权边界。将框架用于商业目的前，必须核对当前许可证并取得所需授权；本 skill 不替代法律或授权审查。

## 2. RQAlpha 的运行结构

`rqalpha.run_func()` 解析配置后进入 `rqalpha.main.run()`。关键顺序是：

1. 创建 `Environment`。
2. 加载并启动系统 Mod 和自定义 Mod。
3. 如果 Mod 没有设置 `env.data_source`，创建默认 `BaseDataSource`。
4. 基于 DataSource 创建 `DataProxy`、交易日历和事件源。
5. 执行策略生命周期并由 broker/matcher 处理订单。
6. analyser Mod 汇总组合、成交和风险指标。

因此本地数据源必须在自定义 Mod 的 `start_up()` 中调用：

```python
env.set_data_source(LocalRQDataSource(...))
```

策略函数的职责：

- `init(context)`：初始化参数、状态和初始 universe；只执行一次。
- `before_trading(context)`：当日盘前准备；此时日线历史默认截止到前一交易日。
- `open_auction(context, bar_dict)`：处理集合竞价阶段。
- `handle_bar(context, bar_dict)`：处理当前 bar。日线回测每日调用一次。
- `after_trading(context)`：盘后记录和检查。

## 3. 最小策略

下面的策略只用于验证数据和撮合链路，不能作为投资策略：

```python
from pathlib import Path

from rqalpha import run_func
from rqalpha.api import history_bars, order_target_percent, update_universe


def init(context):
    context.stock = "000001.XSHE"
    context.checked = False
    update_universe([context.stock])


def handle_bar(context, bar_dict):
    if not context.checked:
        closes = history_bars(
            context.stock,
            5,
            "1d",
            "close",
            skip_suspended=True,
            include_now=True,
            adjust_type="pre",
        )
        assert len(closes) == 5
        assert abs(closes[-1] - bar_dict[context.stock].close) < 1e-8
        context.checked = True
        order_target_percent(context.stock, 0.5)


output_dir = Path("cache/backtests/local-smoke/2024-01")
output_dir.mkdir(parents=True, exist_ok=True)

run_result = run_func(
    init=init,
    handle_bar=handle_bar,
    config={
        "base": {
            "start_date": "2024-01-02",
            "end_date": "2024-01-31",
            "frequency": "1d",
            "accounts": {"stock": 1_000_000},
            "rqdatac_uri": "disabled",
        },
        "mod": {
            "local_rqdata": {
                "enabled": True,
                "lib": "rqalpha_mod_local_rqdata",
                "priority": 40,
                "warehouse_path": "cache/rqdata/warehouse.duckdb",
            },
            "sys_analyser": {
                "enabled": True,
                "benchmark": None,
                "output_file": str(output_dir / "result.pkl"),
                "plot": False,
            },
        },
    },
)

result = run_result["sys_analyser"]
assert not result["trades"].empty
print(result["summary"])
```

本地 Mod 位于项目根目录 `rqalpha_mod_local_rqdata`。如果出现 `No module named 'rqalpha_mod_local_rqdata'`，重新运行注册脚本；不要在策略中临时修改 `sys.path`。

## 4. 推荐配置

### base

- `start_date/end_date`：必须落在行情和交易日历交集内。
- `frequency`：首版固定 `1d`。
- `accounts.stock`：股票账户初始资金。
- `rqdatac_uri`：本地模式固定为 `disabled`。
- `capital_gain_tax_rate`：A 股股票回测通常保留 0；不要把它误当印花税配置。
- `auto_update_bundle`：本地数据源模式设为 `False`。

### sys_simulation

- `matching_type`：日线可用 `current_bar` 或 `vwap`。两者都可能使用当日完整 bar；必须结合信号时点判断是否产生前视偏差。
- `price_limit`：保持 `True`，使用 `limit_up/limit_down` 限制成交。
- `volume_limit`：建议保持 `True`，并显式设置 `volume_percent`。
- `inactive_limit`：保持 `True`；停牌仍必须额外由 `v_suspension` 控制。
- `slippage_model/slippage`：显式记录，不能依赖未记录的默认值。

### sys_transaction_cost

- `stock_min_commission`：默认 5 元。
- `stock_commission_multiplier`：RQAlpha 股票基础佣金率上乘以该倍率。
- `tax_multiplier`：印花税倍率。
- `pit_tax`：需要历史真实印花税率时启用并单独回归测试。

### sys_analyser

- `benchmark`：应由本地数据源提供对应指数行情；没有时设为 `None`，不能静默替代。
- `output_file`：输出 pickle 结果。
- `report_save_path`：RQAlpha 原生报告为 CSV；本项目研究衍生数据仍优先保存 Parquet。若生成 CSV 报告，应只把它视作框架输出，不作为规范数据层。
- `plot`：自动化运行固定 `False`，需要图时使用保存路径而非阻塞式窗口。

`run_func()` 返回的是各 Mod 的结果字典。分析结果位于 `run_result["sys_analyser"]`，其中当前 6.3.0 提供 `summary`、`trades`、`portfolio`、账户与持仓表；不要假设 analyser 返回顶层 `orders`。

## 5. 时间语义与复权

`history_bars` 的默认 `adjust_type` 是 `pre`。策略必须显式填写，避免代码阅读者猜测：

- `none`：不复权；用于与撮合 bar、涨跌停价格和原始行情核对。
- `pre`：前复权；常用于计算连续历史信号。
- `post`：后复权；必须验证复权锚点语义。

日线回测中：

- `before_trading` 获取日线历史时，截止到前一交易日。
- `handle_bar` 中 `include_now=True` 才明确包含当前日 bar。
- 如果信号依赖当日收盘价，就不能同时假设以同一收盘价无摩擦成交。应改为下一交易时点成交，或明确这是信号模式近似并单独标注偏差。

本地规范行情是不复权价格。复权历史必须使用 `v_adj_factor`，不能用 `prev_close` 代替复权因子。

## 6. 交易约束和费用

验收至少覆盖：

- 100 股 `round_lot` 和卖出零股规则。
- T+1 `market_tplus`。
- 停牌日不可成交。
- 涨停买入、跌停卖出限制。
- 无成交量 bar 的限制。
- 成交量占比限制。
- 佣金、最低佣金、印花税和滑点。
- 分红导致现金变化。
- 拆股/送转导致持仓数量与成本变化。

不要只检查收益曲线。应直接检查 `orders`、`trades`、`positions`、`portfolio` 和事件日前后的现金。

## 7. 因子与横截面数据

RQAlpha DataSource 主要负责引擎需要的市场数据。项目自有因子可采用两种方式：

1. 在自定义 Mod 中用 `register_api` 暴露只读查询 API。
2. 在策略的 `before_trading` 中按当前可用日期批量读取 DuckDB，并缓存当日横截面。

不要在每个证券、每个 bar 上单独查询 DuckDB。按日期批量读取横截面，按证券懒加载时序行情。

连接规则：

- 日频估值/换手率：按 `(date, order_book_id)`。
- 行业/指数快照：按 `snapshot_date <= signal_date` 向后 as-of。
- 新闻：按发布时间映射到下一可交易时点；盘后新闻不能进入当日收盘前信号。
- 财务：按公告日或实际可用日，不按报告期提前连接。

## 8. 输出与复现实验

每次正式运行保存：

- 完整 config。
- 策略源文件或代码哈希。
- RQAlpha、Python、DuckDB 版本。
- `warehouse.duckdb` 路径和各依赖视图最大日期。
- 参数、随机种子（如有）和运行时间。
- analyser 的结果 pickle。
- 关键质量检查结果。

推荐目录：

```text
cache/backtests/<strategy_name>/<run_id>/
  config.json
  metadata.json
  result.pkl
  checks.json
```

## 9. 分层验收

1. Preflight：环境、仓库和视图存在。
2. DataSource 单测：instrument、交易日历、单 bar、历史 bars、复权、停牌/ST、分红、拆股。
3. 单证券 smoke：短区间可下单、成交、持仓和结算。
4. 事件回归：选择已知停牌、涨跌停、分红、拆股日期逐项核对。
5. 横截面回归：验证历史股票池和 as-of 快照。
6. 全量性能：记录启动耗时、峰值内存和每回测年耗时。
7. 研究审计：样本内/外边界和参数搜索记录正确。

## 10. 常见错误

- `future_info.json`、`stocks.h5` 或 `instruments.pk` 缺失：自定义 Mod 未成功注入，RQAlpha 回退到了默认 bundle 数据源。
- `No module named 'rqalpha_mod_local_rqdata'`：本地 Mod 尚未注册，运行 `install_local_mod.py`。
- `history_bars` 长度不足：预热区间不够、停牌过滤后不足，或 `include_now` 理解错误。
- bar 能读取但订单不成交：检查停牌、涨跌停、inactive、volume limit、资金和 round lot。
- 指数 benchmark 报错：本地适配器只注册了股票，未注册 `v_index_instruments/v_index_daily_bar`。
- 除权日前后净值跳变：复权因子、分红或拆股接口至少有一项映射错误。
- 回测日期被自动裁剪：`available_data_range()` 或交易日历范围小于 config 日期。
- 性能极慢：`get_bar()` 在每次调用时执行 DuckDB SQL，没有按证券/日期缓存。

## 11. 官方资料

- RQAlpha 仓库：https://github.com/ricequant/rqalpha
- Mod 开发：https://rqalpha.readthedocs.io/zh-cn/latest/development/mod.html
- 扩展数据源：https://rqalpha.readthedocs.io/zh-cn/develop/development/data_source.html
- 基础 API：https://rqalpha.readthedocs.io/zh-cn/develop/api/base_api.html
- `run_func` 示例：https://rqalpha.readthedocs.io/zh-cn/latest/notebooks/run-rqalpha-in-ipython.html

文档站当前部分页面标为 6.1.x/6.2.x。本项目实现契约以虚拟环境中 RQAlpha 6.3.0 的 `rqalpha/interface.py`、`rqalpha/main.py` 和系统 Mod 默认配置为准。
