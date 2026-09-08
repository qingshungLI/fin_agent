#!/usr/bin/env python3
"""分析已完成的研究结果 - 深入诊断结构质量"""

import json
import pandas as pd
from pathlib import Path

# 读取最新的运行结果
artifacts = Path("artifacts_competition")
latest_run = sorted([d for d in artifacts.iterdir() if d.is_dir()])[-1]

print("=" * 80)
print(f"分析运行: {latest_run.name}")
print("=" * 80)
print()

# 读取report
report_path = latest_run / "report.md"
if report_path.exists():
    print("### 报告摘要 ###")
    print(report_path.read_text(encoding="utf-8"))
    print()

# 分析每个结构
structure_dirs = sorted([d for d in latest_run.iterdir() if d.is_dir() and d.name.startswith("S-")])

for struct_dir in structure_dirs:
    print("=" * 80)
    print(f"结构: {struct_dir.name}")
    print("=" * 80)

    # 读取result.json
    result_path = struct_dir / "result.json"
    if result_path.exists():
        with open(result_path, "r", encoding="utf-8") as f:
            result = json.load(f)

        # 基本信息
        print(f"\n名称: {result['name']}")
        print(f"判定: {result['verdict']}")
        print(f"形式: Form {result['form']} (Family {result['family']})")

        # 测量结果
        measurement = result['measurement']
        print(f"\n### 测量结果 ###")
        print(f"IC (h=5): {measurement['contribution_sum']:.6f}")
        print(f"覆盖率: {measurement['coverage']:.2%}")
        print(f"观测数: {measurement['observations']:,}")
        print(f"交易日数: {measurement['dates']}")
        print(f"胜率: {measurement['hit_rate']:.2%}")

        # IC曲线（不同horizon）
        print(f"\n### IC曲线（多周期）###")
        for curve in measurement['curves']:
            h = curve['horizon']
            ic = curve['mean']
            se = curve['se']
            t = curve['t']
            p = curve['p']
            print(f"  h={h:2d}: IC={ic:.6f} ± {se:.6f}, t={t:.2f}, p={p:.4f}")

        # 分层收益
        print(f"\n### 分层超额收益 (h=5) ###")
        curve_h5 = [c for c in measurement['curves'] if c['horizon'] == 5][0]
        groups = curve_h5['groups']
        for i, ret in enumerate(groups, 1):
            print(f"  Q{i}: {ret*100:+.3f}%")
        print(f"  多空: {(groups[-1] - groups[0])*100:+.3f}%")

        # 稳定性检查
        if 'stability' in measurement:
            print(f"\n### 稳定性（5折交叉验证）###")
            stability = measurement['stability']
            print(f"一致性: {stability['consistent']}")
            for fold in stability['folds']:
                print(f"  Fold {fold['fold']}: IC={fold['mean']:.6f}, t={fold['t']:.2f}, p={fold['p']:.4f}")
        else:
            print(f"\n### 稳定性（5折交叉验证）###")
            print("未找到stability字段（可能在result.json的其他位置）")

        # 安慰剂
        print(f"\n### 安慰剂检验 ###")
        placebo = result['blades']['placebo']
        print(f"状态: {placebo['state']}")
        print(f"原因: {placebo.get('reason', 'N/A')}")
        if placebo['tests']:
            for test in placebo['tests']:
                print(f"  {test['kind']}: p={test['p']:.4f}, state={test['state']}")

        # 阻塞原因
        print(f"\n### 确认阻塞原因 ###")
        confirmation = result['confirmation']
        print(f"可确认: {confirmation['eligible']}")
        for reason in confirmation['reasons']:
            print(f"  - {reason}")

        # 机制假设
        print(f"\n### 机制假设 ###")
        structure = result['structure']
        print(f"机制: {structure['mechanism']}")
        print(f"标签: {structure['labels']}")
        print(f"操作表达式:")
        for expr in structure['operational']:
            print(f"  - {expr}")

        print()

print("=" * 80)
print("分析完成")
print("=" * 80)
print()
print("### 关键洞察 ###")
print("1. 检查IC是否在多个horizon上都显著为正")
print("2. 检查5折交叉验证是否一致")
print("3. 检查分层收益Q5-Q1是否单调")
print("4. 如果安慰剂untested，需要增加n_placebo到>=100")
print("5. 如果要正式确认，需要切换到formal模式")
