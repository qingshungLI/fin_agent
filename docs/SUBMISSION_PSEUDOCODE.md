# AURORA 核心研究流程伪代码

版本：2026-09-09。本文是当前完整引擎的阅读摘要，具体准入、冻结和统计判定以代码为准。历史详细设计见 code.zip 中的 PSEUDOCODE.md；其中标注为历史设计的段落不代表当前成果。

## 输入与输出

输入：授权市场数据、研究配置、模型凭据、研究预算，以及可选的父批次。
输出：冻结合同、测量结果、断言状态、父子谱系、检查点、研究记录与报告。

## 主流程

```text
RESEARCH(config, data, run_id):
    校验配置、数据资格与执行环境
    获取项目写锁；读取或初始化检查点
    若恢复：核对代码、数据、环境、配置及冻结身份
    构造历史字段与未来标签分离的市场面板
    初始化机制坐标任务，或恢复已有队列与研究记忆

    WHILE 队列非空 AND 未超研究预算:
        在安全检查点边界处理暂停／停止请求
        task <- 按当前调度规则选择种子、子代或记忆探针
        proposal <- 使用获准上下文提出机制假设
        specification <- 操作化、逻辑审查、DSL 与字段校验

        IF 提案失败或规格非法:
            按入口策略记录拒绝或确定性回退及其来源
            更新尝试计数与检查点
            CONTINUE（若无法形成合法合同）

        contract <- 冻结机制、三个表达式、周期、覆盖与必要断言
        冻结谱系、数据／代码／配置身份及测量前断言概率
        evidence <- 在探索段执行统计测量与必要检验
        保留支持、矛盾、未知及无效检验状态
        原子提交测量结果和检查点

        reconciled <- 依据确定性断言结果核对证据
        training_hints <- 仅从获准训练段获取方向与条件线索
        children <- 按深度、去重、预算及审查要求构造后续假设
        记录 parent、donor、operator、depth 和父子比较
        将合法后续任务加入队列；不继承父代的有效性

        在规定阶段更新研究记忆与后续探针
        归纳或后处理失败时保留已提交测量，以便恢复
        持久化检查点、研究记录与审计事件

    导出批次报告与结构证据
```

## 条件与方向演化

```text
EVOLVE(parent, training_hints):
    方向来自训练统计；完整条件路径来自训练条件发现
    可选动作包括条件、反向、交互、表达迁移与跨机制迁移
    所有动作均生成新的探索假设
    重新进行机制审查、DSL 校验与冻结
    不允许把事后解释写回事前先验
    不允许读取 B/H 结果来选择本轮方向或条件
```

## 独立确认

```text
CONFIRM_ONCE(frozen_batch, segment ∈ {B, H}):
    在读取该时间段前检查批次准入与审计状态
    核验冻结代码、数据、配置和研究对象身份
    按协议执行单次测量与必要断言检验
    使用冻结批次 Holm 校正及联合规则生成判定
    持久化访问事实与确认结果
```

fast 探索不授予正式确认；实验性 e 轨迹不参与正式判定。当前归档未完成独立确认。

## 核心代码定位

| 研究职责 | 实现 |
|---|---|
| 主流程与恢复 | engine/pipeline.py、engine/continuation.py |
| 结构合同与 DSL | engine/catalog.py、engine/dsl.py、engine/forms.py |
| 六类模型角色与输入白名单 | engine/llm.py |
| 统计测量、断言与安慰剂 | engine/metrics.py、engine/blades.py、engine/placebo.py |
| 条件发现与演化 | engine/discovery.py、engine/evolution.py、engine/cycle.py |
| 研究记忆与规律 | engine/memory.py、engine/laws.py |
| 冻结审计与独立确认 | engine/audit.py、engine/confirmation.py |
| 自有数据独立入口 | research_sdk/ |

SDK 使用独立实验合同，不调用完整引擎的全部模型角色；其验证状态不能与 B/H 确认混用。
