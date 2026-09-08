#!/usr/bin/env python3
"""真实研究运行脚本 - 用于产出可用因子的完整研究流程

策略选择：
1. 使用formal模式 - 完整统计检验
2. n_placebo=200 - 平衡速度和统计显著性（p<0.01需要至少100次）
3. n_boot=500 - 减半但仍足够
4. 测试5个预设结构 - 覆盖主要形式
5. quarantine模式 - 标记数据问题但不阻止运行

预期运行时间：约30-60分钟（取决于硬件）
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from engine.config import ResearchConfig
from engine.cycle import research_cycle

# 配置：formal模式但降低重复次数加速
config = ResearchConfig(
    mode="formal",
    start="2016-07-01",
    end="2022-06-30",
    max_symbols=0,  # 全市场
    seed=20260908,
    n_boot=500,     # 降低到500加速（formal默认1000）
    n_placebo=200,  # 降低到200加速（formal默认500）
    n_trees=500,
    n_splits=20,
    max_structures=5,  # 测试5个结构
    min_effect=0.05,
    workers=4,  # 使用4个worker加速
    industry_policy="quarantine",  # 隔离模式，不因数据问题阻断
    cache=True,
    auto_evolve=False,  # 先不自动进化，只测试预设的
    provider="manual"
)

print("=" * 80)
print("真实研究运行 - Formal模式（降速版）")
print("=" * 80)
print(f"配置：")
print(f"  模式: {config.mode}")
print(f"  日期范围: {config.start} 至 {config.end}")
print(f"  Bootstrap重复: {config.n_boot}")
print(f"  安慰剂重复: {config.n_placebo}")
print(f"  最大结构数: {config.max_structures}")
print(f"  Worker数: {config.workers}")
print(f"  数据策略: {config.industry_policy}")
print("=" * 80)
print()

# 运行研究循环
result = research_cycle(config)

print()
print("=" * 80)
print("运行完成")
print("=" * 80)
print(f"Session: {result['session']}")
print(f"完成结构数: {len(result.get('structures', []))}")
print(f"输出目录: artifacts/{result['session']}/")
print()
print("查看结果：")
print(f"  - 报告: artifacts/{result['session']}/report.md")
print(f"  - 规律账本: artifacts/{result['session']}/law.md")
print(f"  - 因子文件: artifacts/{result['session']}/S-*/research-factor.parquet")
