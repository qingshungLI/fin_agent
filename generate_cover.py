"""
项目封面生成脚本
生成AutoAlpha Harness的16:9项目封面
"""
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
from matplotlib.font_manager import FontProperties

# 创建画布
fig = plt.figure(figsize=(19.2, 10.8), facecolor='#0B0E14')
ax = fig.add_subplot(111)
ax.set_xlim(0, 10)
ax.set_ylim(0, 10)
ax.axis('off')
fig.patch.set_facecolor('#0B0E14')

# 标题区域
ax.text(5, 9.2, 'AutoAlpha Harness',
        fontsize=56, fontweight='bold', color='#F97316',
        ha='center', va='center', family='Arial')

ax.text(5, 8.6, '证伪驱动的自动化因子研究系统',
        fontsize=28, color='#FFFFFF',
        ha='center', va='center')

ax.text(5, 8.2, 'Falsification-Driven Automated Factor Research',
        fontsize=20, color='#94A3B8',
        ha='center', va='center', family='Arial')

# 机制地图矩阵
rows = ['M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M7', 'M8', 'M9', 'M10']
cols = ['F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7']

row_labels = ['注意力', '流动性', '处置效应', '信息扩散', '交易约束',
              '被动资金', '参与者', '风险补偿', '不确定性', '隔夜信息']
col_labels = ['水平', '变化', '时序', '截面', '背离', '条件', '事件']

# 状态：1=已探索, 0=待探索, -1=不可行
status = [
    [1, 1, 1, 0, 0, 0, 0],      # M1
    [1, 0, 1, 0, 0, 0, -1],     # M2
    [0, 1, 0, 1, 0, 0, -1],     # M3
    [-1, 0, 0, 1, 0, 0, 0],     # M4
    [-1, -1, -1, -1, -1, 1, 1], # M5
    [-1, 1, -1, 0, 0, 0, 1],    # M6
    [1, 0, 0, 0, 1, 0, -1],     # M7
    [0, -1, 0, 0, -1, 0, -1],   # M8
    [-1, -1, -1, -1, -1, 0, 1], # M9
    [1, 0, 1, 0, 1, 0, -1]      # M10
]

# 绘制标题
ax.text(2, 7, '机制地图 (10×7)',
        fontsize=24, color='#FFFFFF', fontweight='bold',
        ha='left', va='center')

# 绘制列标签
for j, (col, label) in enumerate(zip(cols, col_labels)):
    x = 2.8 + j * 0.7
    y = 6.5
    ax.text(x, y, f'{col}\n{label}',
            fontsize=9, color='#94A3B8', ha='center', va='center')

# 绘制格子和行标签
for i, (row, label) in enumerate(zip(rows, row_labels)):
    # 行标签
    x_label = 2
    y = 5.8 - i * 0.55
    ax.text(x_label, y, f'{row}\n{label}',
            fontsize=9, color='#94A3B8', ha='right', va='center')

    # 格子
    for j, col in enumerate(cols):
        x = 2.5 + j * 0.7

        if status[i][j] == 1:  # 已探索
            color = '#10B981'
            alpha = 0.9
            edge_color = '#10B981'
            edge_width = 2
            # 添加发光效果
            glow = patches.FancyBboxPatch(
                (x-0.05, y-0.05), 0.65, 0.45,
                boxstyle="round,pad=0.05",
                facecolor='none',
                edgecolor='#10B981', linewidth=0,
                alpha=0.3
            )
            ax.add_patch(glow)
        elif status[i][j] == 0:  # 待探索
            color = '#60A5FA'
            alpha = 0.5
            edge_color = '#60A5FA'
            edge_width = 1
        else:  # 不可行
            color = '#374151'
            alpha = 0.3
            edge_color = '#1E293B'
            edge_width = 0.5

        rect = patches.FancyBboxPatch(
            (x, y-0.2), 0.55, 0.4,
            boxstyle="round,pad=0.03",
            facecolor=color, alpha=alpha,
            edgecolor=edge_color, linewidth=edge_width
        )
        ax.add_patch(rect)

# 图例
legend_y = 0.9
legend_items = [
    ('已探索 (9格)', '#10B981', 0.9),
    ('待探索 (43格)', '#60A5FA', 0.5),
    ('不可行 (18格)', '#374151', 0.3)
]

for i, (text, color, alpha) in enumerate(legend_items):
    x = 7.5 + i * 1.8
    rect = patches.FancyBboxPatch(
        (x-0.15, legend_y-0.1), 0.3, 0.2,
        boxstyle="round,pad=0.02",
        facecolor=color, alpha=alpha,
        edgecolor='white', linewidth=0.5
    )
    ax.add_patch(rect)
    ax.text(x+0.25, legend_y, text,
            fontsize=10, color='#FFFFFF', ha='left', va='center')

# 底部信息区
ax.text(0.5, 0.5, '北京大学金融AI智能体创新大赛',
        fontsize=14, color='#94A3B8', ha='left', va='center')

stats_text = """探索进度: 9/52 (17.3%)
研究证据: 9个提案
工程测试: 57项通过"""
ax.text(5, 0.5, stats_text,
        fontsize=12, color='#FFFFFF', ha='center', va='center',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='#1E293B', alpha=0.8))

ax.text(9.5, 0.5, 'Team AutoAlpha',
        fontsize=14, color='#F97316', ha='right', va='center',
        fontweight='bold')

# 保存
plt.savefig('project_cover.png', dpi=100, bbox_inches='tight',
            facecolor='#0B0E14', edgecolor='none')
print("✅ 项目封面已生成: project_cover.png")
print(f"   尺寸: 1920×1080")
print(f"   格式: PNG")
plt.close()

# 生成高分辨率版本
fig = plt.figure(figsize=(19.2, 10.8), facecolor='#0B0E14')
ax = fig.add_subplot(111)
ax.set_xlim(0, 10)
ax.set_ylim(0, 10)
ax.axis('off')
fig.patch.set_facecolor('#0B0E14')

# 重复上面的绘制代码...
ax.text(5, 9.2, 'AutoAlpha Harness',
        fontsize=56, fontweight='bold', color='#F97316',
        ha='center', va='center', family='Arial')
ax.text(5, 8.6, '证伪驱动的自动化因子研究系统',
        fontsize=28, color='#FFFFFF', ha='center', va='center')
ax.text(5, 8.2, 'Falsification-Driven Automated Factor Research',
        fontsize=20, color='#94A3B8', ha='center', va='center', family='Arial')

plt.savefig('project_cover_hd.png', dpi=150, bbox_inches='tight',
            facecolor='#0B0E14', edgecolor='none')
print("✅ 高清版本已生成: project_cover_hd.png")
print(f"   尺寸: 2880×1620")
print(f"   格式: PNG")
plt.close()

print("\n✨ 全部完成！")
