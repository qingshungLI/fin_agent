# 代码清理记录（2026-09-09）

清理依据为当前入口、代码引用、配置契约和测试职责，而非只看文件是否被 import。独立 CLI、数据接入工具、校准脚本和回归测试都可能不被业务模块直接导入。

## 删除的过时实现

| 删除文件 | 原因 | 保留入口或替代验证 |
| --- | --- | --- |
| `run_real_research.py` | 调用不存在的 `engine.cycle.research_cycle`，导入时直接执行，沿用过时配置 | `run_engine.py` |
| `run_competition.py` | 重复组装引擎配置，仍宣称 manual 有九个种子，默认关闭发现和演化 | `run_engine.py --engineering` 或 `--fast --full-grid` |
| `analyze_results.py` | 固定读取 `artifacts_competition` 的最后一个目录，空目录会异常，导入即执行 | `scripts/summarize_research.py` 与控制台结构证据 |
| `scripts/evaluate_frozen_priors.py` | 针对旧批次与旧提案缓存的固定执行实验，不是通用研究入口 | 完整引擎的冻结、测量和恢复流程 |
| `scripts/validate_proposal_forms.py` | 依赖指定旧批次、缓存及真实付费模型的一次性提案实验 | `tests/test_cycle.py`、`tests/test_research_contracts.py`；真实模型由明确配置的引擎运行 |
| `scripts/validate_form_registration.py` | 固定读取旧 priors/cuts，空结果可错误视作全部通过 | DSL 与形式契约回归测试 |
| `scripts/validate-memory.py` | 导入即采样，仅检查早期四结构运行，输出目录未初始化 | `scripts/validate_memory_recovery.py`、`validate_stage_c_recovery.py` 及记忆回归测试 |
| `scripts/validate-discovery.py` | 导入即运行大型实验，仅覆盖早期强交互 smoke check | `tests/test_discovery_parallel.py`、`test_heterogeneity_evolution.py` 与 ICM 校准 |
| `scripts/benchmark_discovery_runtime.py` | 动态加载未入库的历史实现副本，无法从干净仓库重建 | 当前发现回归测试与 `scripts/benchmark_discovery_parallel.py` |
| `scripts/benchmark_ic_runtime.py` | 已完成优化的重复 IC 实现，假设全量缓存恰好只有一个 | `engine.metrics.daily_ic` 与研究契约测试 |
| `scripts/start-workbench.sh` | 启动 8000 的旧 API，而当前 Vite 代理使用 8001 的控制台 API | Windows 启动脚本或下方直接启动方式 |

根目录六份未纳入 Git 的 `scratch_diagnose_iaaft*.py` 属于本地临时文件，已被 `.gitignore` 排除，本轮保留而不纳入交付。通用诊断脚本 `scripts/diagnose_iaaft_quality.py` 保留。

## 保留的必要内容

- `engine/`、`composition/`、`research_sdk/` 及数据源/执行适配器：实际研究依赖与对外功能。
- `tests/` 的关键回归，以及 `backtest/rqpull/tests/` 的数据采集测试；不是为减少数量而删掉保护。
- `scripts/run_full_validation.py` 及其五个子验证：正式统计校准和记忆恢复的独立职责，不能用普通 pytest 替代。
- 全流程驱动、监控、恢复脚本及其测试：目前仍有独立入口及调用关系。
- 报告构建、封面生成与宣传材料：仍在交付使用，未与过时研究实现一起删除。
- 现有历史产物及冻结哈希：未修改；本次清理不删除引擎模块。

Linux 或 macOS 可在激活项目环境后使用现有入口启动控制台，无需旧脚本：

```bash
npm ci
npm run build
python -m uvicorn dashboard_server:app --host 127.0.0.1 --port 8001
```

以上是本机展示服务启动方式，不等同于多租户生产部署。
## 清理时发现并修复的兼容问题

扩大到数据采集模块后发现，`rqpull/io.py`、`migrate_csv.py`、`repair.py`、`tasks/update.py` 使用了 Python 3.11 无法解析的嵌套 f-string 引号。SQL 路径转义现在先计算再插值，兼容项目声明的解释器版本，也能处理含单引号的目录。

另修复了年度增量更新的分区字段问题：读取旧 `year=...` 分区时，DuckDB 自动推断出额外 year 列，造成第二次更新的 UNION 列数不一致。更新入口显式关闭这一步的 Hive 分区列推断，并在原有 `test_update.py` 中补了同年覆盖写入测试。

这些修复不改动市场数据。额外 SQL 验证使用系统临时目录和合成数据，覆盖合并、重复更新、代码大小写修复、换手率字段修复和 CSV 迁移。
## 本轮验证结果

- Python：`python -m pytest -q tests backtest/rqpull/tests`，148 通过、4 跳过。
- 浏览器：`npx playwright test --workers=2`，13 通过、1 跳过。
- 前端：`npm run build` 通过；三维按需加载块仍有体积提示。
- 剩余 131 个受版本管理 Python 文件通过 Python 3.11 AST 语法检查。
- 被删文件的执行引用已清除，历史材料中的旧入口已替换；本清单保留旧名称作为删除依据。
- 未重新启动真实研究、正式统计校准或 GPU 验证；跳过项不视为通过。