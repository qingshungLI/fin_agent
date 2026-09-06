# 本地 RQAlpha DataSource 契约

## 目录

1. 推荐架构
2. Mod 注入
3. 必需数据映射
4. 方法契约
5. numpy dtype
6. 复权实现
7. 查询与缓存
8. 不支持边界
9. 测试矩阵

## 1. 推荐架构

将适配器实现为项目根目录下的独立包：

```text
rqalpha_mod_local_rqdata/
  __init__.py
  mod.py
  data_source.py
  stores.py
tests/
  test_local_rqdata_source.py
```

职责边界：

- `mod.py`：创建并注入 DataSource，退出时关闭只读连接。
- `data_source.py`：实现 RQAlpha `AbstractDataSource` 契约，不承载 SQL 细节。
- `stores.py`：DuckDB 查询、日期转换、structured array 构造和缓存。
- 测试：用仓库中的确定性证券/事件日期验证接口和引擎行为。

首版只支持 `INSTRUMENT_TYPE.CS` 和日线。指数 benchmark 可作为下一小步加入 `INDX`。

## 2. Mod 注入

`rqalpha_mod_local_rqdata/__init__.py`：

```python
__config__ = {
    "enabled": False,
    "priority": 40,
    "warehouse_path": "cache/rqdata/warehouse.duckdb",
    "cache_bars": True,
}


def load_mod():
    from .mod import LocalRQDataMod
    return LocalRQDataMod()
```

`mod.py`：

```python
from rqalpha.interface import AbstractMod

from .data_source import LocalRQDataSource


class LocalRQDataMod(AbstractMod):
    def __init__(self):
        self.data_source = None

    def start_up(self, env, mod_config):
        self.data_source = LocalRQDataSource(
            warehouse_path=mod_config.warehouse_path,
            base_config=env.config.base,
        )
        env.set_data_source(self.data_source)

    def tear_down(self, code, exception=None):
        if self.data_source is not None:
            self.data_source.close()
```

包名必须遵循 `rqalpha_mod_<name>`。通过 config 中的 `lib: rqalpha_mod_local_rqdata` 加载。不要修改 RQAlpha 自带 `BaseDataSource`。

## 3. 必需数据映射

| RQAlpha 数据 | 本地视图 | 关键字段 |
|---|---|---|
| 股票合约 | `v_instruments` | `order_book_id, symbol, type, exchange, listed_date, de_listed_date, round_lot, board_type, market_tplus, status` |
| 指数合约（可选） | `v_index_instruments` | 同类 instrument 字段 |
| 股票日线 | `v_daily_bar` | `date, open, high, low, close, volume, total_turnover, limit_up, limit_down` |
| 指数日线（可选） | `v_index_daily_bar` | 日线 OHLCV 与成交额 |
| 交易日历 | `v_trading_calendar` | `date` |
| 复权因子 | `v_adj_factor` | `ex_date, ex_cum_factor` |
| 停牌 | `v_suspension` | `date, is_suspended` |
| ST | `v_st_flag` | `date, is_st` |
| 分红 | `v_dividend` | 公告、登记、除息、支付日期及税前现金分红 |
| 拆股/送转 | `v_split` | `ex_dividend_date, split_coefficient_from, split_coefficient_to` |
| 集合竞价 | `v_open_auction` | `datetime, last, volume, total_turnover, limit_up, limit_down` |
| 无风险利率 | `v_yield_curve` | `date` 与期限列 |

所有查询使用只读 DuckDB 连接。启动时检查视图和字段；字段缺失应立即失败，不能返回全空结果。

## 4. 方法契约

### `get_instruments(id_or_syms=None, types=None)`

返回 `rqalpha.model.instrument.Instrument` 序列。`id_or_syms` 可按 `order_book_id` 或 symbol 过滤，并优先于 `types`。

要求：

- 股票 `type` 映射为 `CS`。
- 日期保持 RQAlpha Instrument 能解析的时间类型。
- 不过滤已退市证券。
- `round_lot` 缺失时不能盲目默认为 100；先记录异常并验证证券类型。

### `get_trading_calendars()`

返回：

```python
{TRADING_CALENDAR_TYPE.CN_STOCK: pandas.DatetimeIndex(dates)}
```

日历必须排序、去重、时区语义一致。不能从有行情的日期反推日历。

### `available_data_range(frequency)`

`1d` 返回 `v_daily_bar` 的最小、最大日期。其他频率首版抛 `NotImplementedError`。若加入指数，应返回所有引擎必需数据真实可用范围的交集，不要夸大覆盖。

### `get_bar(instrument, dt, frequency)`

日线返回指定日期的 numpy structured scalar 或兼容 dict。至少包含：

```text
datetime, open, close, high, low, volume,
total_turnover, limit_up, limit_down
```

`datetime` 使用 RQAlpha 6.3.0 的 `YYYYMMDD000000` 整数，例如 `20240102000000`。bar 不存在时返回 `None`，不能向前填充价格。

### `history_bars(...)`

当前 RQAlpha 6.3.0 完整签名：

```python
def history_bars(
    self,
    instrument,
    bar_count,
    frequency,
    fields,
    dt,
    skip_suspended=True,
    include_now=False,
    adjust_type="pre",
    adjust_orig=None,
):
    ...
```

实现要求：

- `dt` 右边界和 `include_now` 语义与 RQAlpha DataProxy 对齐。
- `bar_count=None` 返回可用的全部历史。
- `fields` 支持单字符串、列表和 `None`；单字段返回一维 ndarray。
- `skip_suspended=True` 使用 `v_suspension`，不能只用 `volume == 0`。
- `adjust_type` 支持 `none/pre/post`；未知值立即报错。
- 返回时间升序；不足 `bar_count` 时返回真实可用长度，不伪造 bar。
- 首版只接受 `1d`。如果实现 `1w`，从交易日历和日线确定性聚合并单独测试周边界。

### `is_suspended(order_book_id, dates)`

返回与 `dates` 等长的 `list[bool]`。来源 `v_suspension`。缺失状态不能静默当作 `False`；应区分证券尚未上市、已退市、数据缺口和正常非停牌。

### `is_st_stock(order_book_id, dates)`

返回与 `dates` 等长的 `list[bool]`。来源 `v_st_flag`。按历史日期读取，禁止用当前 ST 状态回填历史。

### `get_dividend(instrument)`

无记录返回 `None`；有记录返回 structured array：

```text
book_closure_date           int64 YYYYMMDD
announcement_date           int64 YYYYMMDD
dividend_cash_before_tax    float64
ex_dividend_date            int64 YYYYMMDD
payable_date                int64 YYYYMMDD
round_lot                   float64
```

本地 `declaration_announcement_date` 映射到 `announcement_date`。日期空值处理必须与 RQAlpha 持仓模型测试，不可转换成随机或负整数。

### `get_split(instrument)`

无记录返回 `None`；有记录返回：

```text
ex_date         int64 YYYYMMDD000000
split_factor    float64
```

计算：

```python
split_factor = split_coefficient_to / split_coefficient_from
```

分母为 0、空值或结果非正时立即报数据错误。

### `get_yield_curve(start_date, end_date, tenor=None)`

返回以日期为 index 的 DataFrame，范围两端闭合。`tenor` 不为空时只返回指定期限列。列名如 `1y`、`10y` 必须保留字符串。

### `get_open_auction_bar(instrument, dt)`

从 `v_open_auction` 返回集合竞价 bar。将 `last` 作为竞价成交价，并返回 `datetime, open, limit_up, limit_down, volume, total_turnover`。`last=0` 且 `volume=0` 表示未形成竞价成交，不能替换为日线开盘价。

### `get_open_auction_volume(instrument, dt)`

返回同一集合竞价记录的 `volume`，缺失时遵循引擎可识别的无数据语义并测试；不要伪造日线成交量。

### 其他日线股票路径可能调用的方法

- `get_share_transformation(order_book_id)`：没有换股数据时返回 `None`。
- `get_exchange_rate(...)`：仅人民币市场时返回符合 RQAlpha `ExchangeRate` 约定的 1:1 汇率对象；先检查 6.3.0 类型定义，不能只返回裸数字。
- `current_snapshot(...)`：若日线引擎路径需要，基于当前日 bar 构造兼容 snapshot；先用 smoke test确认实际调用。

任何未支持的分钟、tick、期货接口明确抛 `NotImplementedError`。

## 5. numpy dtype

日线建议 dtype：

```python
DAY_BAR_DTYPE = np.dtype([
    ("datetime", np.uint64),
    ("open", np.float64),
    ("close", np.float64),
    ("high", np.float64),
    ("low", np.float64),
    ("volume", np.float64),
    ("total_turnover", np.float64),
    ("limit_up", np.float64),
    ("limit_down", np.float64),
])
```

分红和拆股 dtype 必须与 `rqalpha/interface.py` 文档完全一致。构造后测试 `dtype.names`、字段类型、排序和空数组行为。

## 6. 复权实现

可复用：

```python
from rqalpha.data.base_data_source.adjust import adjust_bars
```

本地因子转换为：

```python
EX_CUM_FACTOR_DTYPE = np.dtype([
    ("start_date", np.uint64),
    ("ex_cum_factor", np.float64),
])
```

映射 `ex_date -> start_date`，日期格式为 `YYYYMMDD000000`。若首条不是起始基准，按 RQAlpha 6.3.0 `BaseDataSource.get_ex_cum_factor()` 的行为补基准记录；不要凭经验猜基准值，直接与源码和 `v_return_calibration` 校准。

至少验证：

- 非除权日 `none/pre/post` 的相对变化一致。
- 除权日收益与 `v_return_calibration.official_return` 一致。
- 前复权最后一点、后复权第一点锚定符合预期。
- `adjust_orig` 改变时结果符合 RQAlpha 语义。
- `get_bar()` 保持不复权，复权只影响历史 API。

## 7. 查询与缓存

推荐两级访问：

1. 启动时加载 instrument、交易日历和数据范围。
2. 首次访问证券时，一次读取该证券所需区间的 bars、复权因子和事件并转成排序 ndarray。

横截面策略可按日期或年份批量缓存。缓存键至少包含证券、频率、数据版本或仓库更新时间；数据下载仍在进行时，不得跨更新复用旧缓存。

DuckDB 查询全部参数化：

```python
connection.execute(
    "SELECT * FROM v_daily_bar WHERE order_book_id = ? ORDER BY date",
    [order_book_id],
)
```

不要拼接证券代码或日期到 SQL。关闭 Mod 时关闭连接。

## 8. 不支持边界

首版以下方法可抛 `NotImplementedError`：

- `history_ticks`
- 分钟/tick `current_snapshot`
- `get_trading_minutes_for`
- `get_merge_ticks`
- `get_settle_price`
- `get_futures_trading_parameters`
- `get_algo_bar`

但必须先通过调用跟踪确认日线股票 smoke test 不会走到这些分支。错误消息应写明“仅支持 A 股股票日线”，方便定位。

## 9. 测试矩阵

### 接口单测

- instrument 总数、已退市样本、symbol 查询和类型过滤。
- 日历有序、唯一且范围正确。
- 单证券首日、普通日、末日和不存在日期的 bar。
- `fields` 三种形式、`bar_count=None`、`include_now` 两种状态。
- `skip_suspended` 两种状态。
- `none/pre/post` 和 `adjust_orig`。
- 无/有分红，无/有拆股。
- 无竞价成交和正常竞价成交。

### 引擎回归

- 单证券买入并持有。
- 停牌日下单不成交。
- 涨停买入、跌停卖出不成交。
- 分红前持仓跨除息日。
- 拆股前持仓跨除权日。
- 指数 benchmark（实现指数后）。

### 性能门槛

记录查询次数。短区间单证券回测不应每个交易日重复执行同一证券全历史 SQL；全市场调仓不应形成“日期 × 证券”的逐行 SQL 模式。
