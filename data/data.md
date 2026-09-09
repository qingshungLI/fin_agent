# A 股数据目录说明

本文档根据 `./data` 中现有 Parquet 文件的目录结构、Schema、行数及少量样本生成。盘点时间为 2026-09-06。

## 1. 数据概览

- 数据格式：Parquet。
- 文件数量：920 个 Parquet 文件。
- 总体积：约 1.51 GiB。
- 主体时间范围：2016-07-01 至 2026-07-30；不同数据集的起止日期并不完全一致。
- 年度数据通常按 `year=YYYY/data.parquet` 分区。
- 行业三级快照按 `snapshot=YYYY-MM-DD/data.parquet` 分区。
- 申万行业变更明细按 `industry=行业代码/data.parquet` 分区。
- 股票代码采用 `order_book_id`，例如 `000001.XSHE`、`600000.XSHG`。
- `XSHE` 表示深圳证券交易所，`XSHG` 表示上海证券交易所。
- 除非特别说明，价格字段通常为人民币元，成交额及市值通常为人民币元，成交量通常为股；精确口径仍应以原始数据供应商定义为准。

> 注意：目录内没有附带供应商字段字典。下文中可直接由字段、数值和数据关系确认的内容按实际含义描述；无法仅靠文件严格确认的特殊口径会明确标为“待供应商口径确认”。

## 2. 基础信息

### `instruments.parquet`：A 股证券基本信息

- 记录数：5,562。
- 当前文件中的证券类型均为 `CS`，即普通股票类证券。
- 包含上交所和深交所证券，板块包括主板、创业板和科创板。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `index` | int64 | 导出时保留的原始行索引，不建议作为业务主键。 |
| `order_book_id` | string | 证券唯一标识，带交易所后缀。 |
| `trading_code` | string | 纯数字证券代码。 |
| `symbol` | string | 证券中文简称。 |
| `abbrev_symbol` | string | 证券简称的拼音缩写。 |
| `type` | string | 证券类型；当前为 `CS`。 |
| `exchange` | string | 交易所，`XSHE` 或 `XSHG`。 |
| `status` | string | 当前证券状态，如 `Active`。 |
| `listed_date` | timestamp | 上市日期。 |
| `de_listed_date` | timestamp | 退市日期；未退市时为空。 |
| `board_type` | string | 上市板块：`MainBoard` 主板、`GEM` 创业板、`KSH` 科创板。 |
| `special_type` | string | 特别处理类型，如 `Normal`、`ST`、`StarST`、`PT`、`Other`。 |
| `market_tplus` | int64 | 交易交收/可卖规则中的 T+N 数值；A 股样本为 1。 |
| `round_lot` | double | 标准交易单位，A 股通常为 100 股。 |
| `trading_hours` | string | 常规交易时段。 |
| `industry_code` | string | 公司行业代码，样本形如证监会行业代码；具体版本待确认。 |
| `industry_name` | string | 公司行业名称。 |
| `sector_code` | string | 大类板块英文代码。 |
| `sector_code_name` | string | 大类板块中文名称。 |
| `issue_price` | double | 发行价格。 |
| `office_address` | string | 办公地址。 |
| `province` | string | 所在省份。 |
| `purchasedate` | string | 名为购买日期的源字段；当前样本多为空，精确用途待确认。 |

### `index_instruments.parquet`：指数基本信息

- 记录数：7,872。
- 当前文件中的证券类型均为 `INDX`。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `index` | int64 | 导出时保留的原始行索引。 |
| `order_book_id` | string | 指数唯一标识。 |
| `symbol` | string | 指数中文名称。 |
| `abbrev_symbol` | string | 指数名称拼音缩写。 |
| `type` | string | 类型；当前为 `INDX`。 |
| `exchange` | string | 指数所属交易所。 |
| `status` | string | 指数状态。 |
| `listed_date` | timestamp | 发布或上市日期。 |
| `de_listed_date` | timestamp | 终止日期；仍有效时为空。 |
| `base_date` | timestamp | 指数基日。 |
| `base_point` | double | 指数基点。 |
| `underlying_symbol` | string | 标的代码；不适用时为空。 |
| `market_tplus` | double | T+N 属性。 |
| `round_lot` | double | 交易单位；指数通常仅作行情标识。 |
| `trading_hours` | string | 行情交易时段。 |

### `trading_calendar.parquet`：A 股交易日历

- 记录数：2,448。
- 日期范围：2016-07-01 至 2026-07-30。
- 每行代表一个开市交易日，仅含字段 `date`。

### `yield_curve.parquet`：收益率曲线

- 记录数：2,520。
- 日期范围：2016-07-01 至 2026-07-29。
- 每行是一日的期限结构，样本数值以小数表示，例如 `0.028` 约为 2.8%。
- 文件名未注明曲线品种；它是国债、无风险或其他债券曲线，需要供应商口径确认。

| 字段 | 含义 |
| --- | --- |
| `date` | 曲线日期。 |
| `0s` | 即期/隔夜附近期限，精确定义待确认。 |
| `1m`、`2m`、`3m`、`6m`、`9m` | 1、2、3、6、9 个月期限收益率。 |
| `1y` 至 `10y` | 对应年限的收益率，包含 1、2、3、4、5、6、7、8、9、10 年。部分期限可能为空。 |
| `15y`、`20y`、`30y`、`40y`、`50y` | 对应长期限收益率。 |

### `valuation_factors.parquet`：估值字段清单

- 记录数：8。
- 它不是时间序列，而是 `valuation` 数据集可用字段的枚举表。
- `factor` 的值为：`market_cap`、`market_cap_2`、`a_share_market_val`、`pe_ratio_ttm`、`pb_ratio_lf`、`ps_ratio_ttm`、`pcf_ratio_ttm`、`ev`。

## 3. 股票行情与交易状态

### `daily_bar/`：股票日线行情

- 记录数：10,489,402。
- 日期范围：2016-07-01 至 2026-07-29。
- 粒度：每只股票、每个交易日一行。

| 字段 | 含义 |
| --- | --- |
| `order_book_id` | 股票唯一标识。 |
| `date` | 交易日期。 |
| `open` | 开盘价。 |
| `high` | 最高价。 |
| `low` | 最低价。 |
| `close` | 收盘价。 |
| `prev_close` | 前收盘价。 |
| `limit_up` | 当日涨停价。 |
| `limit_down` | 当日跌停价。 |
| `volume` | 成交量，通常以股计。 |
| `total_turnover` | 成交额，通常以人民币元计。 |
| `num_trades` | 成交笔数。 |
| `year` | 年度分区字段。 |

### `open_auction/`：开盘集合竞价快照

- 记录数：10,339,815。
- 时间范围：2016-07-01 09:24:52 至 2026-07-30 09:25:04.629。
- 从行数和时间样本看，粒度基本为每只股票、每个交易日一条 09:25 左右的集合竞价快照。

| 字段 | 含义 |
| --- | --- |
| `order_book_id` | 股票唯一标识。 |
| `datetime` | 快照时间。 |
| `open` | 当时记录的开盘价。 |
| `last` | 最新成交/撮合价。 |
| `high`、`low` | 快照口径下的最高价、最低价。 |
| `prev_close` | 前收盘价。 |
| `limit_up`、`limit_down` | 当日涨停价、跌停价。 |
| `volume` | 集合竞价成交量。 |
| `total_turnover` | 集合竞价成交额。 |
| `a1` 至 `a5` | 卖一至卖五价格。 |
| `b1` 至 `b5` | 买一至买五价格。 |
| `a1_v` 至 `a5_v` | 卖一至卖五委托量。 |
| `b1_v` 至 `b5_v` | 买一至买五委托量。 |
| `prev_settlement` | 前结算价；股票样本中通常为 0，主要适用于期货类行情结构。 |
| `open_interest` | 持仓量；股票样本中通常为 0。 |
| `year` | 年度分区字段。 |

### `return_calibration/`：官方日收益率校准值

- 记录数：1,054,881。
- 日期范围：2016-07-01 至 2026-07-29。
- `official_return` 为小数收益率。样本与 `close / prev_close - 1` 一致，但该表只覆盖约十分之一的日行情记录，因此更像需要特殊校准的证券日期集合，而不是完整收益率面板；入模前应核实生成规则。

| 字段 | 含义 |
| --- | --- |
| `date` | 交易日期。 |
| `order_book_id` | 股票唯一标识。 |
| `official_return` | 官方/校准后的当日收益率，小数形式。 |
| `year` | 年度分区字段。 |

### `turnover/`：换手率

- 记录数：10,489,401。
- 日期范围：2016-07-01 至 2026-07-29。
- 数值样本表明换手率以百分数表示，例如 `0.4512` 表示约 0.4512%，不是 0.4512 的比例值。

| 字段 | 含义 |
| --- | --- |
| `order_book_id` | 股票唯一标识。 |
| `date` | 交易日期。 |
| `today` | 当日换手率。 |
| `week` | 近一周换手率口径指标。 |
| `month` | 近一月换手率口径指标。 |
| `year_rate` | 近一年换手率口径指标。 |
| `current_year` | 本自然年至今换手率口径指标。 |
| `year` | 年度分区字段。 |

> `week`、`month`、`year_rate`、`current_year` 是区间累计、日均还是其他聚合方式，无法仅凭文件确认。

### `st_flag/`：ST 状态

- 记录数：10,880,665。
- 日期范围：2016-07-01 至 2026-07-30。
- 粒度：股票日。

| 字段 | 含义 |
| --- | --- |
| `date` | 日期。 |
| `order_book_id` | 股票唯一标识。 |
| `is_st` | 是否处于 ST/特别处理状态。 |
| `year` | 年度分区字段。 |

### `suspension/`：停牌状态

- 记录数：10,880,665。
- 日期范围：2016-07-01 至 2026-07-30。
- 粒度：股票日。

| 字段 | 含义 |
| --- | --- |
| `date` | 日期。 |
| `order_book_id` | 股票唯一标识。 |
| `is_suspended` | 当日是否停牌。 |
| `year` | 年度分区字段。 |

## 4. 估值数据

### `valuation/`：股票日频估值指标

- 记录数：10,494,604。
- 日期范围：2016-07-01 至 2026-07-30。
- 粒度：每只股票、每个交易日一行。

| 字段 | 含义 |
| --- | --- |
| `order_book_id` | 股票唯一标识。 |
| `date` | 估值日期。 |
| `market_cap` | 总市值类指标，通常以人民币元计。 |
| `market_cap_2` | 第二种市值口径；与 `market_cap` 接近但并非始终相同，精确定义待供应商确认。 |
| `a_share_market_val` | A 股市值，通常以人民币元计。 |
| `pe_ratio_ttm` | 滚动市盈率，使用过去十二个月利润。亏损公司可能为负值。 |
| `pb_ratio_lf` | 市净率，使用最近一期财务数据。 |
| `ps_ratio_ttm` | 滚动市销率，使用过去十二个月营业收入。 |
| `pcf_ratio_ttm` | 滚动市现率，使用过去十二个月现金流口径；现金流为负时可能出现负值。 |
| `ev` | 企业价值 Enterprise Value；部分记录为空。 |
| `year` | 年度分区字段。 |

## 5. 公司行为与复权

### `dividend/`：现金分红

- 记录数：33,837。
- 除息日期范围：2016-07-07 至 2026-08-07。
- 2026-08 的日期晚于多数行情数据终点，说明表中包含已公告的未来实施事件。

| 字段 | 含义 |
| --- | --- |
| `order_book_id` | 股票唯一标识。 |
| `declaration_announcement_date` | 分红实施公告日期。 |
| `advance_date` | 预案公告日期或首次披露日期，精确口径待确认。 |
| `book_closure_date` | 股权登记日。 |
| `ex_dividend_date` | 除权除息日。 |
| `payable_date` | 派息日。 |
| `dividend_cash_before_tax` | 税前现金红利。 |
| `round_lot` | 分红基准股数；样本中常为每 10 股。 |
| `quarter` | 分红所属报告期，如 `2025q2`。 |
| `year` | 按除息/事件年份组织的分区字段。 |

### `split/`：送转股/拆股事件

- 记录数：4,561。
- 除权日期范围：2016-07-04 至 2026-07-30。

| 字段 | 含义 |
| --- | --- |
| `order_book_id` | 股票唯一标识。 |
| `book_closure_date` | 股权登记日。 |
| `ex_dividend_date` | 除权日；字段沿用了除息日期命名。 |
| `payable_date` | 新增股份到账或可流通日期。 |
| `split_coefficient_from` | 送转前基准股数，例如 10。 |
| `split_coefficient_to` | 送转后股数，例如 20。 |
| `cum_factor` | 累计/本次股本变动因子；样本与 `to / from` 一致。 |
| `year` | 年度分区字段。 |

### `adj_factor/`：价格复权因子事件

- 记录数：34,417。
- 除权日期范围：2016-07-01 至 2026-07-30。
- 每行是一只股票在一次除权除息事件附近的因子记录，不是完整股票日面板。

| 字段 | 含义 |
| --- | --- |
| `order_book_id` | 股票唯一标识。 |
| `ex_date` | 因子生效/除权除息日期。 |
| `announcement_date` | 事件公告日期。 |
| `ex_factor` | 本次事件复权因子。 |
| `ex_cum_factor` | 截至该事件的累计复权因子。 |
| `ex_end_date` | 本段因子的结束日期；当前有效时可能为空。 |
| `year` | 年度分区字段。 |

> 前复权、后复权的乘除方向以及因子在生效日两侧的使用规则，必须结合数据供应商定义验证后再用于价格调整。

## 6. 指数数据

当前专门保存了四个指数：

| 指数代码 | 常用名称 | 数据目录后缀 |
| --- | --- | --- |
| `000300.XSHG` | 沪深 300 | `000300_XSHG` |
| `000905.XSHG` | 中证 500 | `000905_XSHG` |
| `000852.XSHG` | 中证 1000 | `000852_XSHG` |
| `000985.XSHG` | 中证全指 | `000985_XSHG` |

### `index_daily_bar/`：指数日线行情

- 记录数：9,788。
- 日期范围：2016-07-01 至 2026-07-29。
- 当前只包含上述四个指数。

| 字段 | 含义 |
| --- | --- |
| `order_book_id` | 指数代码。 |
| `date` | 交易日期。 |
| `open`、`high`、`low`、`close` | 指数开盘、最高、最低、收盘点位。 |
| `prev_close` | 前收盘点位。 |
| `volume` | 指数成分股汇总成交量口径。 |
| `total_turnover` | 指数成分股汇总成交额口径。 |
| `year` | 年度分区字段。 |

### `index_components_*`：月末指数成分股快照

- 对应目录：`index_components_000300_XSHG/`、`index_components_000905_XSHG/`、`index_components_000852_XSHG/`、`index_components_000985_XSHG/`。
- 快照日期范围：2016-07-29 至 2026-07-30。
- 从每年行数看，通常为月末快照，而非逐日成分表。

| 字段 | 含义 |
| --- | --- |
| `order_book_id` | 成分股代码。 |
| `snapshot_date` | 成分股快照日期。 |
| `index_id` | 所属指数代码。 |
| `year` | 年度分区字段。 |

### `index_weights_*`：月末指数权重快照

- 对应目录：`index_weights_000300_XSHG/`、`index_weights_000905_XSHG/`、`index_weights_000852_XSHG/`、`index_weights_000985_XSHG/`。
- 快照日期范围：2016-07-29 至 2026-07-30。
- `weight` 以小数表示，例如 `0.00409` 代表约 0.409%。

| 字段 | 含义 |
| --- | --- |
| `order_book_id` | 成分股代码。 |
| `weight` | 该成分股在指数中的权重，小数形式。 |
| `snapshot_date` | 权重快照日期。 |
| `index_id` | 所属指数代码。 |
| `year` | 年度分区字段。 |

## 7. 行业分类数据

### `industry_citics/`：中信一级行业月末快照

- 记录数：519,081。
- 快照日期范围：2016-07-29 至 2026-07-30。

| 字段 | 含义 |
| --- | --- |
| `order_book_id` | 股票代码。 |
| `first_industry_code` | 中信一级行业代码。 |
| `first_industry_name` | 中信一级行业名称。 |
| `snapshot_date` | 行业归属快照日期。 |
| `year` | 年度分区字段。 |

### `industry_citics_level3/`：中信一至三级行业月末快照

- 记录数：519,081。
- 分区数：121 个月末快照。
- 快照日期范围：2016-07-29 至 2026-07-29。

| 字段 | 含义 |
| --- | --- |
| `order_book_id` | 股票代码。 |
| `first_industry_code`、`first_industry_name` | 中信一级行业代码和名称。 |
| `second_industry_code`、`second_industry_name` | 中信二级行业代码和名称。 |
| `third_industry_code`、`third_industry_name` | 中信三级行业代码和名称。 |
| `snapshot_date` | 行业归属快照日期。 |
| `source` | 分类版本来源，样本为 `citics_2019`。 |
| `level` | 源数据附带的层级/匹配标记；样本为 0，精确含义待确认。 |

### `industry_chain_citics/`：中信产业链、产业和风格分类

- 记录数：519,082。
- 快照日期范围：2016-07-29 至 2026-07-30。

| 字段 | 含义 |
| --- | --- |
| `order_book_id` | 股票代码。 |
| `industry_sector_name` | 产业板块名称。 |
| `industry_chain_sector_name` | 产业链板块名称。 |
| `style_sector_name` | 风格板块名称。 |
| `snapshot_date` | 分类快照日期。 |
| `year` | 年度分区字段。 |

### `industry_sws/`：申万一级行业月末快照

- 记录数：520,182。
- 快照日期范围：2016-07-29 至 2026-07-30。

| 字段 | 含义 |
| --- | --- |
| `order_book_id` | 股票代码。 |
| `first_industry_code` | 申万一级行业代码。 |
| `first_industry_name` | 申万一级行业名称。 |
| `snapshot_date` | 行业归属快照日期。 |
| `year` | 年度分区字段。 |

### `industry_sws_2021_hierarchy/`：申万 2021 一至三级行业月末快照

- 记录数：520,182。
- 分区数：121 个月末快照。
- 快照日期范围：2016-07-29 至 2026-07-29。

| 字段 | 含义 |
| --- | --- |
| `order_book_id` | 股票代码。 |
| `first_industry_code`、`first_industry_name` | 申万一级行业代码和名称。 |
| `second_industry_code`、`second_industry_name` | 申万二级行业代码和名称。 |
| `third_industry_code`、`third_industry_name` | 申万三级行业代码和名称。 |
| `snapshot_date` | 行业归属快照日期。 |
| `source` | 分类来源；样本为 `sws`。 |

### `industry_sws_2021_exact_changes/`：申万 2021 行业归属有效期明细

- 记录数：11,371。
- 分区数：431 个行业代码。
- 与月末快照不同，本数据集直接保存“股票属于某行业”的起止有效期，适合精确还原任意日期的行业归属。
- `cancel_date=2200-12-31` 可视为“当前仍有效”的哨兵日期，而不是真实业务日期。

| 字段 | 含义 |
| --- | --- |
| `order_book_id` | 股票代码。 |
| `start_date` | 进入该行业的生效日期。 |
| `cancel_date` | 退出该行业的日期；`2200-12-31` 表示尚未退出。 |
| `industry_code` | 申万行业代码，同时也是目录分区键。 |

## 8. 使用时的重要注意事项

1. **避免未来函数**：指数成分、指数权重和行业分类都是历史快照。回测时必须使用交易日当时已经可得的最近快照，不能直接使用最新分类。
2. **状态表比行情表多一天**：`st_flag`、`suspension` 和 `valuation` 已到 2026-07-30，而股票日线目前只到 2026-07-29。连接时应以目标交易日和实际数据可用性为准。
3. **公司行为含未来事件**：现金分红表包含到 2026-08-07 的已公告事件，不能因为记录已存在就假设此前市场已经知晓；应使用公告日期控制信息可得性。
4. **复权口径需验证**：应用 `adj_factor` 前，先用一只发生分红送转的股票核验复权方向和除权日边界。
5. **缺失值不是零**：估值、收益率曲线和公司行为字段中存在空值，不应无条件填 0。
6. **主键建议**：股票日频表通常使用 `(order_book_id, date)`；快照表使用 `(order_book_id, snapshot_date)`；公司行为表可能同日多事件，不应假设 `(order_book_id, ex_date)` 永远唯一。
7. **单位复核**：本文根据样本识别了常见单位，但批量计算前仍建议用成交额约等于成交量乘均价、市值约等于股价乘股本等关系做一次程序化校验。
