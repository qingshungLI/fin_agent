# 服务器运行

唯一代码、数据、环境、测试与产物目录：`bridge-amax:/data1/yuxiao/fin_agent`。本地不需要项目副本。下列操作均在服务器项目目录执行。

## 环境与凭证

- Python 3.11，项目 `.venv`；Node/npm 同样位于 `.venv/bin`。
- `.env` 是服务器私有文件，权限 600，Git 忽略；按 `.env.example` 的变量名配置，不将值写入报告或命令历史。
- `API_KEY` 或 `DEEPSEEK_API_KEY`；官方 HTTPS 地址，模型由 `DEEPSEEK_MODEL` 指定。
- 原始 Parquet 不改写。行情缓存、模型响应、审计、因子、日志、截图均在服务器 `artifacts/`。
- `provider=llm` 由模型生成机制、选择基础信号与方向、提出独立旁证；标签和表达式语法由注册表约束。`hybrid` 是四个固定基线加模型盲押/对齐，不能称为模型自由搜索。

## 运行探索

```bash
cd /data1/yuxiao/fin_agent
export PATH="$PWD/.venv/bin:$PATH"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1

python run_engine.py --run-id my-exploration-01 \
  --provider llm --max-symbols 600 --max-structures 1 --workers 8 \
  --industry-policy quarantine --discovery --bayes
```

`quarantine` 会明确排除行业冲突/未知的股票日期，并屏蔽时间不合规的竞价字段。它只允许继续研究，不能消除正式数据质量阻断。默认 `strict` 遇冲突立即退出。

`--engineering` 使用 100 次 bootstrap、99 次置换和较少树/切分，仅验证流程。99 次置换最小 p=0.01，不能检验 p<0.01，故安慰剂明确返回未测试。省略该参数使用完整计算规模，也不意味着获得正式 PASS。

`--max-symbols 0` 在 CLI 表示全股票池；股票按固定代码哈希取样，不能按效果选样。本轮真实研究主要为 600 只股票、A 段 1458 个交易日。B/H 未用于选因子。

相同 run-id、配置、代码、数据和完整产物可恢复。任意身份变化都必须使用新 run-id，禁止覆盖既有实验。全项目单写者锁阻止并发污染；安慰剂工作进程采用 spawn，避免继承锁。不要删除锁文件来解除活动任务。

## 工作台

```bash
bash scripts/start-workbench.sh
```

服务器回环地址：工作台 `http://127.0.0.1:5173`，API `http://127.0.0.1:8000/docs`。端口已占用时脚本退出，不结束未知进程。通过既有 SSH 转发访问；不会在公网监听。

工作台支持提交受限参数的探索任务、自动刷新状态和查看结构测量。API 同时提供：
- `GET /api/jobs`：最近任务；
- `POST /api/jobs`：JSON 参数 provider、max_symbols、max_structures、workers、engineering、industry_policy、industry_source、auction_policy；
- 运行中提交返回 409；参数无效返回 422；不接受路径、命令或密钥参数。

任务记录/日志位于 `artifacts/jobs/`；服务 PID/日志位于 `artifacts/services/`。

## 产物与结论

每个 `artifacts/<run-id>/` 包含 checkpoint、数据质量、冻结切点、研究报告、结构测量、成本与稳定性、记忆和阻断原因。结构目录内的 `research-factor.parquet` 只是探索信号；不等于可提交、可交易或通过确认的因子。

`engine.confirmation.confirm_once` 在读取 B/H 前检查来源、完整产物、模拟校准、候选资格与一次性授权记录。当前数据和候选未达标，因此不开放工作台一键确认/交易。安慰剂拒绝后，不继续包装机制解释；没有合格季度档案时层次记忆返回不可辨识，没有 B-PASS 时组合保持阻断。

## 验证

```bash
python -m pytest -q
npm run build
npm exec playwright test
# 包含真实模型调用的任务提交验收，仅显式启用时执行
RUN_LIVE_RESEARCH=1 npm exec playwright test
python scripts/validate-statistics.py
python scripts/validate-memory.py
python scripts/validate-discovery.py
python backtest/build_exploration_warehouse.py
python backtest/validate_execution.py
python backtest/validate_split.py
```

浏览器测试使用服务器现有 Chromium。统计模拟只验证所列合成情景，不能替代真实数据质量、独立确认或策略经济性。分红/送转股验证是执行适配器证据，不是因子收益证据。

## RQData 原始来源接入

服务器项目私有 .env 现在支持 RQDATAC_LICENSE。安装可使用项目可选依赖 rqdata，
客户端固定 rqdatac==3.5.6.1。安装附件只做了审阅；没有执行 make.sh，
也没有改写全局 shell profile。不要调用 rqdatac.info() 写入研究日志，
该客户端的 license 登录模式会打印授权内容。

scripts/reconcile_rqdata_industry.py 用少量历史反例直接查询；
scripts/fetch_rqdata_industry_daily.py 只拉取 A 段交易日的行业元数据，
每个日期保留返回文件、请求身份、接收时间和哈希，支持失败后的缓存恢复。
B/H 价格与收益不在拉取范围内。

data/industry_sws_daily 是新增的直接查询数据，原始行业区间文件未覆盖。
A 段共 1458 个交易日、5,479,320 条返回记录；请求证券清单为全部 5562 只股票。
当前供应商对历史有效日的响应不等于当年发布时点的存档版本。

使用新数据并分别指定行业/竞价校验方式：

    python run_engine.py --run-id rqdata-research-NEW \
      --industry-source rqdata_daily --industry-policy strict \
      --auction-policy quarantine --provider hybrid \
      --max-symbols 0 --max-structures 4 --workers 8

industry_policy 不再需要为了解决竞价异常而放宽；auction_policy 省略时
继承原行业策略，以保持旧命令行为。工作台提供对应独立选项。
竞价隔离仍会阻止正式候选晋级，行业通过不代表整个数据集或因子已通过。
