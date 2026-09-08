# RSI Alpha Research Harness

这里的 RSI 是 **Recursive Self-Improvement（递归自我改进）**，不是任何金融技术指标。金融技术指标或其他 alpha seed 只是可以被研究代理提出的一类输入；系统的核心对象是“研究方法如何产生下一代研究方法”。

我们的叙事是：

> AutoAlpha 让 AI 在一个冻结的 alpha 评估器里提出机制、编译成受限 DSL、运行研究、接受批评，再把通过审查的证据反馈给下一轮。每次改进都有预算、父结构、输入哈希、评估指标和 keep/discard/crash 状态，因此评委可以看到改进发生在哪里，也可以复现或否决它。

## 为什么叫 Harness

Harness 把可以变化的研究假设和不能变化的评估协议分开：

- **可变**：机制描述、字段组合、表达式、周期、gate、演化候选。
- **冻结**：数据快照、时间切分、purge、成本、字段准入、评分公式、输出 schema。
- **反馈**：训练段用于选择父结构；验证段在候选全部冻结后读取；失败原因回到 critic，不直接回写成更优参数。
- **边界**：代数、候选数、运行时间和模型调用均有限；系统不会自我复制，也不会宣称无限升级。

这借鉴 autoresearch 的工程骨架：固定评估约束、每次只运行一个受限实验、用单一可比指标做 keep/discard，并记录 crash；原项目明确把固定时间预算、固定 evaluator 和 `keep/discard/crash` 作为实验协议的一部分。citeturn0search0turn0search1 我们把它改造成 alpha 研究协议：固定时间切分和成本，而不是用训练分钟数代替金融有效样本。

## 六步闭环

```text
PROPOSE → COMPILE → MEASURE → CRITICIZE → MUTATE → RECORD
   ↑                                                   ↓
   └────────────── 有限预算 + 父结构 + 审计证据 ──────────────┘
```

1. **PROPOSE**：DeepSeek 角色或企业用户提交机制格子。
2. **COMPILE**：受限 DSL 检查字段、量纲、窗口、未来字段和数据准入。
3. **MEASURE**：只读冻结面板，完成训练 IC、验证 IC、覆盖和目标路径。
4. **CRITICIZE**：检查验证子区间、成本、同暴露基准、相似度和数据失败。
5. **MUTATE**：只从训练段证据派生下一代，例如 lag、平滑、cross-family、gate；每个候选都有 parent。
6. **RECORD**：持久化 `keep/discard/crash/untested`、耗时、哈希和失败原因。

当前 `research_sdk.autoresearch.run_self_improvement_harness` 生成固定 alpha seed 只是一个演示：它的 `autoresearch.json` 已记录代数、评估器策略、训练段选择和验证读取顺序。正式框架的 RSI 循环由比赛引擎中的 DeepSeek proposer、reviewer、reconciler、inducer 和自动演化队列共同实现。

## 前端如何讲给评委

进入 `#studio` 后，页面顶部会显示 RSI loop：

- 研究代理提出假设。
- DSL 编译器保护数据和时间边界。
- 固定评估器产生 IC、成本和回撤。
- Critic 记录支持、反驳、未知。
- Mutation 产生有限下一代。
- Ledger 展示 keep/discard/crash。

页面把“研究方法进步”和“因子收益变好”分开。某个候选验证收益为正，只能成为待复验候选；只有研究协议本身成功通过独立复现实验，才能声称 RSI 闭环有效。

## 演示脚本

1. 从 `#studio` 上传企业面板。
2. 编辑 RSI loop 中的三个 alpha seed，说明 RSI 指递归自我改进，不是某个金融指标。
3. 运行 fast，查看 C001... 的 parent、训练指标和验证指标。
4. 打开 `autoresearch.json`，展示 `generation=0`、训练段选择和 keep/discard。
5. 回到比赛控制台，展示 DeepSeek 角色如何提出下一代结构、失败如何保留、组合 gate 如何读取已完成结构。
6. 最后强调：预算、验证集和正式资格都由 harness 固定，不由 AI 自己修改。