# AURORA 主办方提交说明

**项目名称：AURORA Alpha Harness — 可审计的自演化量化研究智能体**

让每一次因子探索，都留下可追溯的证据。

## 项目简介

AURORA 将机制假设、受限表达式、实验冻结、统计检验、假设演化和研究记忆连接成可运行的量化研究流程。大模型按六类角色协作，确定性计算模块负责测量与检验；研究人员通过控制台审查批次、父子谱系和证据。系统同时提供自有数据 SDK，便于本地试用与集成。

三个主要设计贡献是：将机制语义绑定到可执行研究合同；将训练段方向与条件线索转换成重新冻结的子代；将支持、冲突和未知保留为研究记忆与后续调度输入。它们是系统设计与实现贡献，相对方法增益仍需同预算消融验证。

## 附件阅读顺序

1. `项目说明.md`：项目定位、附件导航和使用方法。
2. `AURORA_项目演示.pptx` 或同名 PDF：12 页架构演示。
3. `AURORA_技术报告.pdf`：详细方法、架构与证据边界。
4. `核心流程伪代码.md`：当前研究主流程与代码定位。
5. `code.zip`：核心代码、控制台源码、配置与测试。
6. `项目公开介绍.md`：摘要、创新点和拟议落地路径，可用于提报页面。
7. `项目封面.png`：用户原始 16:9 品牌封面。
8. `MANIFEST.json`：源码版本、各附件 SHA256 和代码文件清单。

## 核心代码范围

`code.zip` 包含 engine、composition、research_sdk、控制台后端与 React 源码、数据接入和回测适配器、研究运行/恢复/校准脚本、测试及依赖配置。代码包使用源码白名单构建，不含原始行情、模型凭据、虚拟环境、node_modules、缓存及运行产物。

当前为源码交付。完整研究需要用户提供授权数据和模型凭据，安装依赖不会自动获得这些资源。源码包可独立进行合成数据工程测试；完整市场研究、独立确认和交易验证有额外数据与配置前提。

## 从代码包开始

解压 code.zip，进入 code 目录，推荐 Python 3.11。

```powershell
py -3.11 -m venv .venv-research
.\.venv-research\Scripts\python.exe -m pip install -e ".[test,backtest,bayes]"
.\.venv-research\Scripts\python.exe -m pip install -e backtest/rqalpha_mod_local_rqdata
.\.venv-research\Scripts\python.exe -m pytest -q tests backtest/rqpull/tests
npm ci
npm run build
.\.venv-research\Scripts\python.exe -m uvicorn dashboard_server:app --host 127.0.0.1 --port 8001
```

浏览器访问本机 8001 端口。没有历史产物时控制台显示空批次，可使用自有数据入口；完整研究入口为 `run_engine.py`，参数和数据契约见代码包 README.md、RUN_PIPELINE.md、docs/DELIVERY.md 和 skills/factor-research/SKILL.md。

`.env.example` 仅含空凭据模板。实际凭据应自行配置，不能随提交包分发。某些扩展测试需要 GPU、真实批次或额外依赖；跳过条件以各测试为准。

## 当前证据状态

2026-09-09 停止快照收录 15 个完成候选、6 个已评估子代；9 个 UNDECIDABLE、6 个 FAIL，独立确认数为 0。Core Lab 截图属于另外一组阶段性证据，不合并计算候选数量，不将训练区域 IC 换算成收益提升倍数。

技术报告和演示中的待执行消融方案不计为已完成实验。原始封面的统计公式表达设计动机，实际能力与确认状态以报告正文和冻结产物为准。

## 提报时填写

团队名称、成员姓名与分工、联系人及联系方式由团队在主办方页面填写。本包没有代填身份信息，也未代替团队向赛事平台上传。
