"""报告制图管线：读取归档 JSON 和截图转录，生成矢量图、PNG 预览与来源哈希。

图形只复述已提供证据；Core Lab 截图与引擎批次分开呈现，不生成推断置信区间。
在仓库根目录执行；输出固定到 docs/figures，供 XeLaTeX 编译引用。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "figures"
INK, TEAL, BLUE, GOLD = "#19344B", "#238E86", "#497EA9", "#BE8743"
plt.rcParams.update(
    {
        "font.family": "Microsoft YaHei",
        "font.size": 10,
        "axes.unicode_minus": False,
        "pdf.fonttype": 42,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)


def save(name: str) -> None:
    """保存当前画布的矢量图和预览，假设输出目录已创建。

    Args:
        name: 不含扩展名的报告图名称。

    Returns:
        None，PDF 与 PNG 写入固定输出目录。
    """
    plt.savefig(OUT / f"{name}.pdf", bbox_inches="tight", facecolor="white")
    plt.savefig(OUT / f"{name}.png", bbox_inches="tight", dpi=160, facecolor="white")
    plt.close()


def box(
    ax: Axes, x: float, y: float, title: str, detail: str, color: str = BLUE, width: float = 3.5
) -> None:
    """在固定网格上绘制架构节点，文字长度需适配设计宽度。

    Args:
        ax: 已设置网格范围的画布坐标系。
        x: 节点左下角横坐标。
        y: 节点左下角纵坐标。
        title: 节点标题。
        detail: 单行说明。
        color: 边框与标题颜色。
        width: 节点宽度，单位为设计坐标。

    Returns:
        None，节点添加至 ax。
    """
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            1.12,
            boxstyle="round,pad=0.02,rounding_size=.12",
            edgecolor=color,
            facecolor="#F4F8FA",
            linewidth=1.1,
        )
    )
    ax.text(x + 0.18, y + 0.77, title, color=color, fontsize=12, weight="bold")
    ax.text(x + 0.18, y + 0.27, detail, color=INK, fontsize=9)


def arrow(
    ax: Axes,
    start: tuple[float, float],
    end: tuple[float, float],
    color: str = BLUE,
    curve: float = 0,
) -> None:
    """连接已定位节点，假设调用者将端点放在节点边缘。

    Args:
        ax: 已设置网格范围的画布坐标系。
        start: 连线起点。
        end: 连线终点。
        color: 连线颜色。
        curve: 弧线曲率，零表示直线。

    Returns:
        None，连线添加至 ax。
    """
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=13,
            linewidth=1.4,
            color=color,
            connectionstyle=f"arc3,rad={curve}",
        )
    )


def architecture() -> None:
    """从本地实现的固定模块关系绘制架构，无运行数据输入。

    Returns:
        None，保存包含反馈与确认边界的架构图。
    """
    _, ax = plt.subplots(figsize=(12, 7.6))
    ax.set(xlim=(-0.2, 12), ylim=(-0.5, 7.2))
    ax.axis("off")
    ax.text(0, 6.8, "AURORA / 研究控制平面与证据平面", fontsize=19, color=INK, weight="bold")
    box(ax, 0, 5.0, "01  数据与可得时间", "只读 Parquet · 行业/资格掩码 · A/B/H")
    box(ax, 4.1, 5.0, "02  模型研究代理", "机制提案 · 表达式收敛 · 审查 / 盲下注")
    box(ax, 8.2, 5.0, "03  冻结执行协议", "受限 DSL · 断言 · 哈希 · 成本")
    box(ax, 8.2, 2.9, "04  确定性测量", "IC 曲线 · placebo · 稳定性 · 增量")
    box(ax, 4.1, 2.9, "05  训练段条件发现", "交叉拟合 · honest 浅森林 · 条件路径", TEAL)
    box(ax, 0, 2.9, "06  递归研究调度", "方向 / 条件 / 交互 · 父子关系 · 深度", TEAL)
    box(ax, 0, 0.6, "证据存储与审计", "result · law · checkpoint · SQLite", INK)
    box(ax, 4.1, 0.6, "用户与 Agent 入口", "控制台 / API · 自有数据 SDK / Skill", INK)
    box(ax, 8.2, 0.6, "独立确认与组合", "B/H 准入 · 多结构 Gate · 执行核验", GOLD)
    for a, b in [
        ((3.5, 5.56), (4.1, 5.56)),
        ((7.6, 5.56), (8.2, 5.56)),
        ((9.95, 5), (9.95, 4.02)),
        ((8.2, 3.46), (7.6, 3.46)),
        ((4.1, 3.46), (3.5, 3.46)),
    ]:
        arrow(ax, a, b)
    arrow(ax, (1.75, 4.02), (4.65, 5), TEAL, 0.24)
    ax.text(0.05, 4.45, "训练证据生成新假设", fontsize=9, color=TEAL)
    arrow(ax, (1.75, 2.9), (1.75, 1.72), INK)
    arrow(ax, (3.5, 1.16), (4.1, 1.16), INK)
    arrow(ax, (9.95, 2.9), (9.95, 1.72), GOLD)
    ax.text(10.1, 2.23, "受门槛约束", fontsize=9, color=GOLD)
    ax.text(
        0,
        -0.1,
        "冻结边界：AI 不修改评估器，不将验证统计反馈为下一代训练先验。",
        color=INK,
        fontsize=11,
    )
    save("architecture")


def evolution() -> None:
    """绘制当前有界演化协议，无参数，预算说明与仓库配置对应。

    Returns:
        None，保存包含重新冻结边界的闭环图。
    """
    _, ax = plt.subplots(figsize=(12, 5.4))
    ax.set(xlim=(-0.2, 12), ylim=(-0.4, 5))
    ax.axis("off")
    ax.text(
        0, 4.65, "RSI / 改进下一轮研究问题，而非修改评估规则", fontsize=18, color=INK, weight="bold"
    )
    nodes = [
        (0, 2.8, "冻结父结构", "parent · operator · depth"),
        (4.1, 2.8, "训练段诊断", "方向稳定性 · 条件路径 · 父子增量"),
        (8.2, 2.8, "选择演化动作", "condition / reverse / interaction"),
        (8.2, 0.6, "新子代重新冻结", "机制审查 · DSL · 断言 · 数据权限"),
        (4.1, 0.6, "同协议重新测量", "未完成保持未知 · 失败保留证据"),
        (0, 0.6, "更新记忆与队列", "有界预算 · 最大深度 2 · 去重"),
    ]
    for x, y, title, detail in nodes:
        box(ax, x, y, title, detail, TEAL if y == 0.6 else BLUE)
    for a, b in [
        ((3.5, 3.36), (4.1, 3.36)),
        ((7.6, 3.36), (8.2, 3.36)),
        ((9.95, 2.8), (9.95, 1.72)),
        ((8.2, 1.16), (7.6, 1.16)),
        ((4.1, 1.16), (3.5, 1.16)),
        ((1.75, 1.72), (1.75, 2.8)),
    ]:
        arrow(ax, a, b, TEAL)
    ax.text(
        0,
        -0.1,
        "70 个初始坐标 + 140 次额外额度；4 个冷启动后优先异质性子代，每四次保留种子探索。",
        fontsize=10,
        color=INK,
    )
    save("evolution")


def results(snapshot: dict[str, Any], case: dict[str, Any]) -> None:
    """绘制两组独立来源的阶段统计，不生成推断区间。

    Args:
        snapshot: 含候选 IC、区间和状态的归档 JSON。
        case: 从用户原图转录的区域 IC 与切分统计。

    Returns:
        None，分别保存归档结果图和截图案例图。
    """
    rows = snapshot["candidates"]
    _, ax = plt.subplots(figsize=(10.5, 5))
    for index, row in enumerate(rows):
        ic = row["primary_ic"]
        color = TEAL if row["verdict"] == "UNDECIDABLE" else GOLD
        ax.plot([ic["ci_low"], ic["ci_high"]], [index, index], color=color, linewidth=2)
        ax.scatter(ic["mean"], index, color=color, s=38, zorder=3)
    ax.axvline(0, color="#A7B5BF", linewidth=1)
    ax.set_yticks(range(len(rows)), [r["candidate"] + " · " + r["verdict"] for r in rows])
    ax.invert_yaxis()
    ax.set_xlabel("A 段主要 IC 与归档 bootstrap 区间（非独立确认）")
    ax.set_title(
        "11 个已完成候选 / 6 个未知、5 个未通过", loc="left", pad=18, color=INK, weight="bold"
    )
    ax.grid(axis="x", alpha=0.16)
    plt.tight_layout()
    save("archived_results")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.7), gridspec_kw={"width_ratios": [1, 1.6]})
    values = [case["parent_ic"], case["child_ic"], case["remainder_ic"]]
    axes[0].bar(
        ["父结构", "条件子结构", "其余区域"], values, color=[BLUE, TEAL, "#A7B5BF"], width=0.6
    )
    for i, value in enumerate(values):
        axes[0].text(i, value + 0.006, f"{value:.4f}", ha="center", fontsize=10)
    axes[0].set_ylim(0, 0.19)
    axes[0].set_title("训练段区域对照", loc="left", color=INK, weight="bold")
    splits = case["splits"]
    axes[1].bar(
        range(len(splits)),
        [r["ic"] for r in splits],
        color=[BLUE, TEAL] + ["#9FBACA"] * 4,
        width=0.6,
    )
    axes[1].set_xticks(range(len(splits)), [r["name"] + f"\n{r['days']} 日" for r in splits])
    for i, row in enumerate(splits):
        axes[1].text(i, row["ic"] + 0.01, f"{row['ic']:.3f}", ha="center", fontsize=9)
    axes[1].set_ylim(0, 0.49)
    axes[1].set_title("短窗口与重复切分：仅描述性复核", loc="left", color=INK, weight="bold")
    for ax in axes:
        ax.set_ylabel("IC")
        ax.grid(axis="y", alpha=0.16)
        ax.set_axisbelow(True)
    fig.text(
        0.02,
        0.01,
        "来源：factor_1.png 人工转录；未提供原始序列。重复切分不视为独立 OOS，不绘制推断置信区间。",
        fontsize=9,
        color=INK,
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    save("corelab_case")


def main() -> None:
    """从仓库固定来源构建报告图片和清单，无参数，缺失来源时报错。

    Returns:
        None，生成四组图片并记录来源哈希和逐候选统计。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    source = ROOT / "docs/research/2026-09-09-results.json"
    transcript = ROOT / "report/evidence-transcription.json"
    snapshot = json.loads(source.read_text(encoding="utf-8"))
    case = json.loads(transcript.read_text(encoding="utf-8"))
    architecture()
    evolution()
    results(snapshot, case)
    sources = [source, transcript, *sorted((ROOT / "report").glob("*.png"))]
    manifest = {
        "sources": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sources
        },
        "completed": len(snapshot["candidates"]),
        "children_from_lineage": sum(
            bool(row["lineage"].get("parent")) for row in snapshot["candidates"]
        ),
        "independently_confirmed": 0,
        "note": "Top-level evolution counters disagree with per-candidate lineage; preserve source and derive counts from rows.",
    }
    (OUT / "sources.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
