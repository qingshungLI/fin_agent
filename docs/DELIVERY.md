# 交付入口与代码导航

本页整理 2026-09-09 本地交付入口。当前交付形态为 Git 源码仓库；控制台依赖仓库中的 `dist/`、文档和研究产物，不能把单独安装 Python 包等同于完整控制台部署。

## 先看哪些文件

| 目的 | 入口 |
| --- | --- |
| 系统叙事、数据范围与研究原则 | [README](../README.md) |
| 当前递归演化机制 | [异质性驱动的假设进化](heterogeneity_evolution.md) |
| 全流程与研究命令 | [RUN_PIPELINE](../RUN_PIPELINE.md) |
| 最新已归档的研究证据 | [9 月 9 日进展](research/2026-09-09-progress.md) |
| 控制台启动与演示 | [CONTROL_PANEL](../CONTROL_PANEL.md) |
| 自有数据接入协议 | [Skill](../skills/factor-research/SKILL.md) |
| 历史设计与实现契约 | [PSEUDOCODE](../PSEUDOCODE.md) |

历史设计和计划不等于当前产出。汇报结果以归档记录及对应批次的冻结文件、检查点和结果文件为准。

## 代码职责

| 路径 | 职责 |
| --- | --- |
| `run_engine.py` | 完整研究 CLI 入口 |
| `engine/pipeline.py`、`engine/cycle.py` | 编排、冻结、测量、检查点和演化队列 |
| `engine/evolution.py` | 从训练异质性证据提出条件、方向和交互子代 |
| `engine/discovery*.py` | 森林条件发现与受内存预算约束的并行切分 |
| `engine/initial_search.py` | Linux 专用的非自适应初始网格并行搜索 |
| `engine/gpu_ridge.py` | 可选 GPU 回归与工作区限制 |
| `composition/` | 多结构组合、门控、评估和执行相关逻辑 |
| `research_sdk/` | 自有数据的独立研究与可复用 API |
| `dashboard_server.py`、`studio_api.py`、`server_jobs.py` | 控制台接口、自有数据接口及任务管理 |
| `src/` | React 控制台、三维研究地图、Skill 与自有数据页面 |
| `tests/`、`tests/browser/` | Python 验证和浏览器验收 |
| `artifacts/` | 本地产物、日志、缓存；不是源码交付目录 |

## 本机检查与展示

在仓库根目录执行，使用项目环境，避免误用系统 Python：

```powershell
.\.venv-research\Scripts\python.exe -m pytest -q
npm ci
npm run build
powershell -ExecutionPolicy Bypass -File scripts/start-control-panel.ps1
```

首次安装项目环境时：

```powershell
py -3.11 -m venv .venv-research
.\.venv-research\Scripts\python.exe -m pip install -e ".[test,backtest,bayes]"
.\.venv-research\Scripts\python.exe -m pip install -e backtest/rqalpha_mod_local_rqdata
```

数据授权、研究数据及模型凭据需要单独配置；安装依赖不会自动获得这些资源。不要把 `.env`、本地环境或原始数据装进展示包。

导航回归使用已启动的 Vite 开发服务（默认 5173），模拟空批次接口，不会启动真实研究：

```powershell
npm run dev -- --host 127.0.0.1
# 另一个终端；首次使用 Playwright 时先执行 npx playwright install chromium
npx playwright test tests/browser/navigation.spec.ts
```

完整浏览器验收还包含真实批次和数据操作，不能用上述单项导航回归代替。Python 测试、前端构建通过也不代表真实全市场研究已完成。

## 平台和研究口径

- Windows 可使用现有主研究入口及发现阶段的 spawn 多进程。新增 `engine.initial_search` 使用 Linux CPU affinity、文件描述符共享锁和 `/proc/meminfo`，其实际运行仍限于 Linux；不要在 Windows 上套用服务器的 40 核命令。
- Skill 中的 `run_experiment` 使用确定性的训练段演化，并记录 `llm_used: false`。完整引擎的模型提案与审查是另一条入口；演示时应明确实际调用的是哪条路径。
- fast、训练方向筛选和正 IC 均不是独立确认。当前归档探索结果不能包装成已经通过全部门槛的可交易因子。
- 更新源码后，旧批次的代码指纹可能不匹配。保留旧产物；按现有恢复协议检查一致性，不修改冻结哈希来强行续跑。