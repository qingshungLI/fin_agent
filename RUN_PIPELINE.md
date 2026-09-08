# 完整研究运行记录

本文件描述 2026-09-08 实际启动的 `fullcycle-20260908`，运行状态以机器产物为准。

| 阶段 | 实际工作 | 产物与判断 |
|---|---|---|
| 1. 依赖与回归 | Python 3.11.9 隔离环境，研究/Bayes/RQAlpha 完整依赖；全量测试及前端构建 | 已通过 70 项测试及前端构建；依赖列表 `artifacts/fullcycle-20260908-environment.txt` |
| 2. 数据与冻结 | 读取 A 段 2016-07-01～2022-06-30，全 5562 只证券、1458 个交易日；派生字段、交易池、行业与竞价质量检查；冻结代码、配置、数据与环境 | `artifacts/fullcycle-20260908/data-quality.json`、`checkpoint.json`、`cuts.json` |
| 3. 初始搜索 | 10 个机制 × 7 种形式，70 格各一次提案尝试；每个提案三种表达式，四个研究周期；登记与事前逻辑审查 | `S-*/proposal.json`、`registration.json`、`frozen.json`；拒绝也消耗尝试次数 |
| 4. 真实测量 | 1000 bootstrap、500 placebo、全市场掩码；必要断言、增量、A 内稳定性和固定成本 | `S-*/result.json`、`daily-ic.parquet`、`research-factor.parquet`；无效替代样本为 untested |
| 5. 自动演化 | 有行动依据的结果触发形状/机制/条件子代；500 棵树、20 个有效切分；最大深度 2；额外 140 次额度 | 子代重新冻结；`followups.json`、`queue.json`、`progress.json`；初始格覆盖额度受保护 |
| 6. 研究记忆 | 每五个结构构建联合季度测量误差、拟合分层记忆、产生探索方向与归纳连接 | `memory-step-*.json`、`induction-*.json`、`laws.json`；不可识别时保持不可识别 |
| 7. 统计校准 | 主检验/Holm 200 次；四类必要断言各 200 次；五类 ICM 场景各 600 次；再做记忆主效应与交互恢复 | `artifacts/validation/full-validation.json` 与各日志；三类推断报告同版本汇总为 `calibration.json`，不校准 e-process 或证明现实数据正确 |
| 8. 独立确认 | A 完成后检查数据质量、检验证据、校准及当前批次新结构资格；符合后才一次性消费 B，再检查 H | 无合格结构则明确 BLOCKED，B/H 保持未读；不能为了跑到终点跳过质量门槛 |
| 9. 执行链路 | A 内真实 RQAlpha 分红与送转窗口；完整批次结束后固定首个已测结构、全 A 段、固定 top-20 投影做工程执行 | 分红现金 136 元、100→150 股送转已对账通过；完整结构执行若有拒单/未成交会明确 FAILED，不换更好看的结构 |
| 10. 收尾 | 汇总新增/继承/拒绝/未解决，保留校准与确认阻塞，以及工程执行结果 | `artifacts/fullcycle-20260908-pipeline/pipeline.json`、`research-summary.md`、执行日志 |

## 正在执行的任务

- 研究：`run_engine.py --full-grid --max-symbols 0 --workers 4 --industry-policy quarantine --auction-policy quarantine --data-profile full --run-id fullcycle-20260908`。
- 独立合成验证：`python -u -m scripts.run_full_validation`。
- 自动收尾：`python -u -m scripts.complete_research_run --run-id fullcycle-20260908 --research-pid <研究PID> --validation-pid <验证PID>`。该命令用于已有进程，不会再次启动搜索。
- 三者均使用 `.venv-research/Scripts/python.exe`。主研究与验证日志分别在 `artifacts/fullcycle-20260908.stdout.log`、`artifacts/full-validation.stdout.log`；异常在对应 stderr 日志。

## 恢复与证据边界

同批次用完全相同的命令恢复。代码、统计设置或依赖版本改变时使用新批次 ID；不要删除检查点或覆盖来源来绕过身份验证。跨批次继承只接受哈希一致的完成结果，不把旧因子记作新独立发现。

完整规模不等于全部阶段必然通过。当前行业与竞价采用隔离策略，因此正式晋级受阻；IAAFT 替代样本频谱不合格也会导致 untested。上述结果必须保留，不允许改成 PASS。工程执行不是独立因子验证，A 段组合回放也不是样本外业绩。