"""论文式架构图管线：按代码职责绘制分区、信息流和反馈边界，导出 PNG/PDF/SVG。

图形只解释架构，不承载生成的实验数据。统一画布便于插入 16:9 PPT，矢量文件可用于报告。
实线表示主流程或结果传递，虚线表示获准反馈；每张图单独说明适用入口及边界。
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import FancyArrowPatch, Rectangle

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/ppt/figures"
INK, TEAL, LIGHT, LINE, MUTED = "#153B40", "#258F86", "#E9F4F0", "#B8CDCC", "#587173"
plt.rcParams.update(
    {
        "font.family": "Microsoft YaHei",
        "font.size": 11,
        "pdf.fonttype": 42,
        "svg.fonttype": "none",
        "axes.unicode_minus": False,
    }
)


def canvas(title: str, caption: str) -> tuple[Figure, Axes]:
    """创建统一论文图画布；输入图题与图注，返回 figure/axes，坐标从上向下。"""
    fig, ax = plt.subplots(figsize=(16, 6.4))
    fig.subplots_adjust(left=0.015, right=0.985, top=0.97, bottom=0.02)
    ax.set(xlim=(0, 16), ylim=(6.4, 0))
    ax.axis("off")
    ax.text(0.25, 0.26, title, color=INK, fontsize=14, weight="bold", va="top")
    ax.plot([0.25, 15.75], [0.72, 0.72], color=LINE, lw=0.8)
    ax.text(0.25, 6.15, caption, color=MUTED, fontsize=9.5, va="center")
    return fig, ax


def region(ax: Axes, x: float, y: float, w: float, h: float, title: str) -> None:
    """绘制带分区标题的容器；输入坐标与标题，返回 None，容器不隐含程序隔离。"""
    ax.add_patch(Rectangle((x, y), w, h, facecolor="#F7FAF9", edgecolor=LINE, lw=0.85))
    ax.text(x + 0.18, y + 0.16, title, fontsize=10.5, color=MUTED, va="top", weight="bold")


def node(
    ax: Axes, x: float, y: float, w: float, h: float, title: str, body: str = "", dark: bool = False
) -> None:
    """绘制模块节点；输入位置与两级文字，返回 None，节点高度需能容纳正文。"""
    ax.add_patch(Rectangle((x, y), w, h, facecolor=INK if dark else LIGHT, edgecolor=TEAL, lw=1))
    ax.text(
        x + w / 2,
        y + 0.22,
        title,
        ha="center",
        va="top",
        color="white" if dark else INK,
        fontsize=12,
        weight="bold",
    )
    if body:
        ax.text(
            x + w / 2,
            y + 0.65,
            body,
            ha="center",
            va="top",
            color="#D6EBE4" if dark else MUTED,
            fontsize=10.5,
            linespacing=1.5,
        )


def edge(
    ax: Axes,
    start: tuple[float, float],
    end: tuple[float, float],
    dashed: bool = False,
    bend: float = 0,
) -> None:
    """绘制有向连接；输入端点、反馈标记与弧度，返回 None，弯曲线用于避开节点。"""
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle="-|>",
            mutation_scale=13,
            color=TEAL,
            lw=1.35,
            linestyle="--" if dashed else "-",
            connectionstyle=f"arc3,rad={bend}",
            shrinkA=2,
            shrinkB=3,
        )
    )


def save(fig: Figure, name: str) -> None:
    """保存同名三种格式；输入画布与文件名，返回 None，PNG 固定为 3840×1536。"""
    for suffix in ("png", "pdf", "svg"):
        fig.savefig(OUT / f"{name}.{suffix}", dpi=240, facecolor="white")
    plt.close(fig)


def architecture() -> None:
    """绘制数据主链与演化反馈；无参数，返回 None，治理条表示贯穿约束。"""
    fig, ax = canvas(
        "图 1  |  AURORA：机制驱动的研究架构",
        "实线：计算与证据传递   ·   虚线：训练线索驱动的新任务   ·   B/H 确认有独立准入；SDK 使用独立实验协议。",
    )
    region(ax, 0.25, 1.05, 15.5, 1.35, "(a) 研究接口与产物消费")
    for x, t, b in [
        (2.2, "研究 CLI", "配置 / 预算 / 批次"),
        (6.3, "控制台与 API", "状态 / 谱系 / 证据"),
        (10.4, "自有数据 SDK", "独立实验合同"),
    ]:
        node(ax, x, 1.52, 3.35, 0.65, t)
    region(ax, 0.25, 2.65, 15.5, 1.85, "(b) 完整引擎：冻结后执行")
    for x, t, b in [
        (0.55, "数据平面", "历史字段与标签分离"),
        (3.65, "研究合同", "机制 / 表达式 / 断言"),
        (6.75, "确定性执行", "测量 / 检验 / 条件发现"),
        (9.85, "研究证据", "结果 / 断言 / 版本身份"),
        (12.95, "独立确认", "冻结批次 / 准入审计"),
    ]:
        node(ax, x, 3.2, 2.5, 1.03, t, b, dark=x == 6.75)
    for x in [3.05, 6.15, 9.25, 12.35]:
        edge(ax, (x, 3.72), (x + 0.6, 3.72))
    edge(ax, (3.8, 2.17), (4.9, 3.17))
    edge(ax, (11.1, 3.17), (8, 2.18))
    node(ax, 1.35, 4.95, 4.3, 0.8, "训练证据 → 子代合同", dark=True)
    node(ax, 6.65, 4.95, 4.3, 0.8, "研究记忆 → 有界队列")
    ax.text(
        12.7,
        5.25,
        "贯穿治理\n角色边界 · 哈希 · 检查点",
        ha="center",
        va="center",
        fontsize=11,
        color=INK,
    )
    edge(ax, (10.6, 4.24), (8.8, 4.95), True)
    edge(ax, (6.65, 5.35), (5.65, 5.35), True)
    edge(ax, (3.3, 4.95), (4.6, 4.24), True)
    save(fig, "01-system-architecture")


def roles() -> None:
    """绘制六角色与信息边界；无参数，返回 None，箭头不暗示六个独立模型投票。"""
    fig, ax = canvas(
        "图 2  |  按职责限制输入的模型协作",
        "六类角色共享模型；字段白名单约束上下文。盲下注用于实验性诊断，结果核对不能改写确定性测量。",
    )
    region(ax, 0.25, 1.08, 9.9, 3.85, "(a) 假设构造、事前预期与冻结执行")
    region(ax, 10.45, 1.08, 5.3, 3.85, "(b) 测量后：消费获准的证据")
    node(ax, 0.65, 1.88, 2.75, 1.25, "提案 proposer", "坐标 / 词表 / 约束\n输出机制假设")
    node(ax, 3.8, 1.88, 2.75, 1.25, "操作化", "字段 / 算子 / 量纲\n输出表达式")
    node(ax, 6.95, 1.88, 2.75, 1.25, "审查 reviewer", "机制 / 断言 / 表达式\n检查逻辑与可测性")
    edge(ax, (3.4, 2.5), (3.8, 2.5))
    edge(ax, (6.55, 2.5), (6.95, 2.5))
    node(ax, 1.1, 3.57, 3.1, 1.0, "盲下注 bettor", "冻结断言概率")
    node(ax, 5.6, 3.57, 3.75, 1.0, "冻结 → 确定性测量", "代码产生数值与断言状态", True)
    edge(ax, (8.35, 3.13), (7.5, 3.57))
    edge(ax, (4.2, 4.05), (5.6, 4.05))
    node(ax, 10.95, 1.88, 4.3, 1.1, "核对 reconciler", "确定性断言结果 → 分类记录")
    node(ax, 10.95, 3.48, 4.3, 1.1, "归纳 inducer", "规律 / 研究后验 → 后续线索")
    edge(ax, (9.35, 4.03), (10.93, 2.57))
    edge(ax, (13.1, 2.98), (13.1, 3.48))
    ax.plot([0.7, 15.3], [5.35, 5.35], color=LINE, lw=0.8)
    ax.text(0.8, 5.65, "提案与盲下注：不接收原始收益或 B/H 观测", fontsize=11, color=TEAL)
    ax.text(9.15, 5.65, "结果后解释：不能回写成事前先验", fontsize=11, color=TEAL)
    save(fig, "02-role-firewall")


def contract() -> None:
    """绘制从语义到冻结产物的编译关系；无参数，返回 None，数学符号仅概括字段。"""
    fig, ax = canvas(
        "图 3  |  研究合同：连接机制语义与确定性评估",
        "Structure = (机制、表达式集合、周期、覆盖、必要断言、谱系)；规格、配置与来源身份共同进入冻结产物。",
    )
    region(ax, 0.25, 1.12, 4.1, 4.68, "(a) 声明式研究对象")
    for y, t, b in [
        (1.75, "机制与研究坐标", "机制族 × 表达形式"),
        (2.92, "表达式与覆盖", "三个操作化 / 主周期"),
        (4.09, "断言与谱系", "必要条件 / parent / operator"),
    ]:
        node(ax, 0.65, y, 3.3, 1.0, t, b)
    region(ax, 4.7, 1.12, 6.0, 4.68, "(b) 验证、编译与冻结")
    for y, t, b in [
        (1.75, "① 语义校验", "词表、可观察性、必要断言"),
        (2.92, "② 受限 DSL 编译", "字段、算子、量纲、窗口与方向"),
        (4.09, "③ 冻结身份", "规格 + 数据 + 代码 + 配置"),
    ]:
        node(ax, 5.15, y, 5.1, 1.0, t, b, dark=y == 4.09)
    edge(ax, (3.95, 3.42), (5.15, 3.42))
    edge(ax, (7.7, 2.75), (7.7, 2.92))
    edge(ax, (7.7, 3.92), (7.7, 4.09))
    region(ax, 11.05, 1.12, 4.7, 4.68, "(c) 可审查的执行产物")
    node(ax, 11.55, 1.75, 3.7, 1.0, "确定性评估", "统计测量 / 必要检验")
    node(ax, 11.55, 3.08, 3.7, 1.0, "证据状态", "支持 / 矛盾 / 未测试")
    node(ax, 11.55, 4.41, 3.7, 1.0, "持久化档案", "冻结规格 / 结果 / 审计")
    edge(ax, (10.25, 4.57), (11.55, 2.25))
    edge(ax, (13.4, 2.75), (13.4, 3.08))
    edge(ax, (13.4, 4.08), (13.4, 4.41))
    save(fig, "03-contract-compilation")


def evolution() -> None:
    """绘制训练驱动的有限递归闭环；无参数，返回 None，确认入口不回流训练选择。"""
    fig, ax = canvas(
        "图 4  |  有界递归：假设可以演化，评估协议保持冻结",
        "方向与条件均为训练选择的新假设；最大谱系深度为 2，任务去重、研究额度与调用预算限制递归规模。",
    )
    region(ax, 0.25, 1.1, 11.2, 4.7, "(a) 探索与演化闭环 / A 段")
    for x, y, t, b in [
        (0.8, 1.92, "父结构", "冻结规格与谱系"),
        (4.5, 1.92, "训练诊断", "方向 / 条件 / 覆盖"),
        (8.2, 1.92, "子代动作", "条件 / 反向 / 交互"),
        (8.2, 4.03, "新研究合同", "审查 / DSL / 重新冻结"),
        (4.5, 4.03, "同协议测量", "结果与父子比较"),
        (0.8, 4.03, "研究记忆", "后验 / 规律 / 队列"),
    ]:
        node(ax, x, y, 2.7, 1.2, t, b, dark=t == "新研究合同")
    edge(ax, (3.5, 2.52), (4.5, 2.52))
    edge(ax, (7.2, 2.52), (8.2, 2.52))
    edge(ax, (9.55, 3.12), (9.55, 4.03))
    edge(ax, (8.2, 4.63), (7.2, 4.63))
    edge(ax, (4.5, 4.63), (3.5, 4.63))
    edge(ax, (2.15, 4.03), (2.15, 3.12), True)
    ax.text(
        5.7,
        3.56,
        "parent · donor · operator · depth",
        ha="center",
        va="center",
        fontsize=11,
        color=TEAL,
    )
    region(ax, 11.8, 1.1, 3.95, 4.7, "(b) 独立确认 / B · H")
    node(ax, 12.25, 1.92, 3.05, 1.2, "确认准入", "冻结批次 / 身份核验")
    node(ax, 12.25, 4.03, 3.05, 1.2, "确认结果", "联合判定 / 审计状态")
    edge(ax, (13.78, 3.12), (13.78, 4.03))
    ax.text(13.78, 5.53, "确认不反哺本轮选择", ha="center", va="center", fontsize=10, color=TEAL)
    save(fig, "04-bounded-evolution")


def main() -> None:
    """输出四张论文式图及说明；无参数，返回 None，所有内容来自既有架构。"""
    OUT.mkdir(parents=True, exist_ok=True)
    for draw in (architecture, roles, contract, evolution):
        draw()
    (OUT / "README.md").write_text(
        "# 论文式架构图\n\n四组 PNG / PDF / SVG；PNG 为 3840×1536，PDF 与 SVG 为矢量。中文字体使用微软雅黑。\n\n图 1 总架构；图 2 六角色信息边界；图 3 研究合同编译；图 4 有界递归与确认。\n\n架构图描述已有协议，不代表性能比较或统计有效性证明。源脚本：scripts/build_paper_diagrams.py。\n",
        encoding="utf-8",
    )
    print("Generated 4 paper-style diagrams in PNG, PDF and SVG")


if __name__ == "__main__":
    main()
