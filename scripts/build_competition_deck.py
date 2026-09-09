"""架构演示构建管线：以共享坐标描述模块和信息流，生成 HTML、原生 PPTX 及讲者备注。

网页复用用户指定 skill 的导航与讲者运行时；架构页用可编辑形状表达真实模块关系。
坐标采用 1600×900 设计画布，正文不依赖外网字体，结果仅作为实现状态的简短说明。
"""

from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/ppt"
BG, FG, ACC, MUTED, PANEL, BORDER = "102B30", "E9F2E9", "72CBC0", "A7C3C5", "173B40", "386064"
Slide = dict[str, Any]


def label(
    s: Slide, x: int, y: int, w: int, h: int, value: str, size: int = 25, color: str = FG
) -> None:
    """登记文字；输入设计像素坐标和文本，返回 None，调用方预留换行高度。"""
    s["elements"].append(dict(kind="text", x=x, y=y, w=w, h=h, text=value, size=size, color=color))


def block(
    s: Slide,
    x: int,
    y: int,
    w: int,
    h: int,
    title: str,
    detail: str,
    code: str = "",
    accent: bool = False,
) -> None:
    """登记模块框及三层文字；输入模块信息，返回 None，代码路径只用于技术页。"""
    s["elements"].append(dict(kind="box", x=x, y=y, w=w, h=h, color=ACC if accent else PANEL))
    color = BG if accent else FG
    label(s, x + 22, y + 17, w - 44, 42, title, 29, color)
    label(s, x + 22, y + 66, w - 44, h - 88, detail, 23, color if accent else MUTED)
    if code and h >= 150:
        label(s, x + 22, y + h - 33, w - 44, 26, code, 16, color if accent else ACC)


def arrow(s: Slide, x: int, y: int, dx: int, dy: int, dashed: bool = False) -> None:
    """登记有方向的信息流；输入端点与位移，返回 None，虚线表示反馈而非调用次序。"""
    s["elements"].append(dict(kind="arrow", x=x, y=y, dx=dx, dy=dy, dashed=dashed))


def page(slug: str, title: str, subtitle: str, layout: str, note: list[str]) -> Slide:
    """创建带稳定 ID 的页面；输入标题及讲述要点，返回空元素页面。"""
    return dict(id=slug, title=title, subtitle=subtitle, layout=layout, notes=note, elements=[])


def content() -> list[Slide]:
    """定义架构叙事及流程图；无参数，返回十二页，统计状态读取固定归档。"""
    slides: list[Slide] = []
    s = page(
        "cover",
        "AURORA Alpha Harness",
        "可审计的自演化量化研究智能体",
        "S01",
        [
            "今天重点介绍架构：研究如何被提出、执行、演化和审计。",
            "沿用项目原始封面；其中 e 轨迹属于实验性诊断，正式判定采用独立确认流程。",
            "递归改进的对象是研究假设与任务分配。",
        ],
    )
    slides.append(s)

    s = page(
        "architecture",
        "系统架构：研究主链、演化反馈与全程治理",
        "数据 → 假设 → 执行 → 证据；演化反馈负责继续研究，治理机制贯穿全程。",
        "S04",
        [
            "先沿中间主链解释输入、研究对象、执行器和产物。",
            "上方是研究控制入口，下方分别是演化反馈和治理约束。",
            "新假设需要重新冻结，不能修改过去的测量结果。",
        ],
    )
    block(
        s,
        85,
        255,
        1430,
        105,
        "研究入口  /  CLI · 控制台 · 自有数据 SDK",
        "定义预算与配置、选择批次、观察研究状态；SDK 具有独立实验口径。",
    )
    for x, t, d, c in [
        (85, "数据平面", "历史字段 / 资格掩码\n未来收益标签分离", "data.py · research_fields.py"),
        (455, "研究合同", "机制 / 表达式\n周期 / 断言 / 谱系", "catalog.py · dsl.py"),
        (825, "确定性执行", "统计测量 / 必要检验\n条件发现 / 成本诊断", "pipeline.py · blades.py"),
        (1195, "证据产物", "冻结版本 / 结果\n研究记录 / 报告", "audit.py · dashboard"),
    ]:
        block(s, x, 405, 320, 195, t, d, c)
    for x in [405, 775, 1145]:
        arrow(s, x, 502, 50, 0)
    block(s, 85, 655, 690, 125, "演化反馈", "训练线索 → 新结构 → 队列调度 → 重新冻结", accent=True)
    block(s, 825, 655, 690, 125, "治理贯穿", "角色输入边界 · 代码/数据指纹 · 检查点 · 确认准入")
    arrow(s, 990, 600, 0, 55, True)
    arrow(s, 615, 655, 0, -55, True)
    slides.append(s)

    s = page(
        "roles",
        "六类角色协作，计算结果由执行器产生",
        "角色分工通过字段白名单落实；同一模型承担多个岗位。",
        "S04",
        [
            "提案、操作化和审查形成可以计算的候选。",
            "盲下注发生在测量前；核对和归纳消费获准的结果与研究记录。",
            "提案与盲下注角色不接收原始收益和 B/H 观测，演化只能传递获准训练线索。",
        ],
    )
    for x, y, t, d, c in [
        (85, 290, "01  提案", "机制坐标、词表、约束\n输出机制假设", "proposer"),
        (585, 290, "02  操作化", "字段、算子、量纲\n输出可执行表达式", "operationalizer"),
        (1085, 290, "03  逻辑审查", "机制、断言、表达式\n审查可观察性与一致性", "reviewer"),
        (85, 565, "04  盲下注", "测量前冻结断言概率\n用于实验性校准诊断", "bettor"),
        (585, 565, "05  结果核对", "消费确定性断言结果\n整理支持、冲突与未知", "reconciler"),
        (1085, 565, "06  研究归纳", "消费规律与研究后验\n组织下一轮探索线索", "inducer"),
    ]:
        block(s, x, y, 430, 180, t, d, c)
    for y in [380, 655]:
        arrow(s, 515, y, 70, 0)
        arrow(s, 1015, y, 70, 0)
    label(
        s,
        85,
        500,
        1400,
        40,
        "测量前：形成假设与预期                 测量后：核对证据与归纳",
        22,
        ACC,
    )
    slides.append(s)

    s = page(
        "contract",
        "研究合同：把经济解释变成可执行对象",
        "Structure 将语义、计算和证据需求绑定在一起。",
        "S08",
        [
            "一个研究对象包含机制、表达式、周期、覆盖、必要断言和谱系。",
            "同机制保留三个表达式，用于检查表达是否一致地指向机制。",
            "DSL 限制字段和算子，模型输出不能作为任意 Python 执行。",
        ],
    )
    block(
        s,
        85,
        280,
        665,
        490,
        "Structure / 最小研究单位",
        "机制坐标       10 类机制 × 7 种形式\n\n操作化          同机制的三个表达式\n\n证据需求       周期、覆盖、必要断言\n\n演化来源       parent / donor / operator / depth",
        "engine/catalog.py",
        True,
    )
    for y, t, d, c in [
        (280, "语义校验", "词表、字段、机制与断言可测性", "catalog.py · forms.py"),
        (465, "DSL 编译", "受限算子、窗口、量纲与方向检查", "dsl.py"),
        (650, "冻结身份", "绑定代码、数据、配置与候选规格", "pipeline.py · audit.py"),
    ]:
        block(s, 895, y, 620, 120, t, d, c)
    arrow(s, 750, 515, 145, 0)
    arrow(s, 1205, 400, 0, 65)
    arrow(s, 1205, 585, 0, 65)
    slides.append(s)

    s = page(
        "execution",
        "评估器：让每项结论都有可核对的来源",
        "机制解释与数值计算分工，检验状态通过确定性代码落盘。",
        "S04",
        [
            "测量、断言、安慰剂、稳定性和条件发现各自产生明确产物。",
            "支持、矛盾和未测试需要分开，未知不被补成通过。",
            "e 轨迹只用于实验性诊断，B/H 独立确认有单独入口。",
        ],
    )
    for j, (t, d, c) in enumerate(
        [
            ("基础测量", "IC、分组与季度表现\nHAC / block bootstrap", "metrics.py"),
            ("必要断言", "方向、形状与条件\nhold / violated / untested", "blades.py"),
            ("安慰剂检验", "置换、时间移位、IAAFT\n有效性与质量诊断", "placebo.py"),
            (
                "稳健性与增量",
                "稳定性、覆盖与成本\n父子和条件结构对照",
                "consistency.py · evolution.py",
            ),
            ("异质性发现", "正交化与浅森林\n训练段完整条件路径", "discovery.py"),
            ("证据提交", "结果、曲线、耗时\n配置与来源身份", "pipeline.py · audit.py"),
        ]
    ):
        block(s, 85 + (j % 3) * 500, 285 + (j // 3) * 265, 430, 205, t, d, c)
    slides.append(s)

    s = page(
        "evolution",
        "自演化：在固定评估器中改进下一轮假设",
        "训练证据提出新问题，所有子代重新进入同一套研究协议。",
        "S14",
        [
            "递归对象是方向、条件、交互及探索队列。",
            "反向线索、完整条件路径和父子比较都来自训练段。",
            "父代失败不阻止提出新假设，但新假设不继承有效性。",
            "最大深度为 2；预算与去重限制探索规模。",
        ],
    )
    for y, t, d in [
        (275, "01  训练线索", "方向诊断、条件覆盖、父子比较"),
        (400, "02  候选动作", "condition / reverse / interaction"),
        (525, "03  新合同", "机制重审、DSL 校验、重新冻结"),
        (650, "04  有界调度", "深度、去重、预算与种子探索"),
    ]:
        label(s, 85, y, 590, 42, t, 29, ACC)
        label(s, 85, y + 49, 590, 50, d, 23)
    for x, y, t, d in [
        (770, 300, "父结构", "冻结规格"),
        (1225, 300, "训练诊断", "可用局部线索"),
        (1225, 600, "子代合同", "重新审查与冻结"),
        (770, 600, "重新测量", "证据进入新一轮"),
    ]:
        block(s, x, y, 290, 145, t, d)
    arrow(s, 1060, 372, 165, 0)
    arrow(s, 1370, 445, 0, 155)
    arrow(s, 1225, 672, -165, 0)
    arrow(s, 915, 600, 0, -155, True)
    slides.append(s)

    s = page(
        "memory",
        "研究记忆：把一次失败变成可复用信息",
        "证据记录、研究后验和任务调度形成反馈；正式判定保持独立。",
        "S05",
        [
            "先保留结构及断言的原始状态，再组织解释。",
            "研究记忆通过分阶段层次贝叶斯服务计划，可识别性不足要明确报告。",
            "后验帮助选择下一探针，不授予确认资格。",
        ],
    )
    for x, t, d, c in [
        (
            85,
            "01  证据记录",
            "支持证据与冲突证据\n未完成检验与拒绝原因\n父子关系与数据身份",
            "laws.py · audit.py",
        ),
        (
            585,
            "02  研究记忆",
            "机制族与表达形式\n分阶段层次贝叶斯\n可识别性和拟合诊断",
            "memory.py",
        ),
        (
            1085,
            "03  后续调度",
            "组织下一探针\n合并有限 follow-up\n带来源地返回队列",
            "cycle.py · continuation.py",
        ),
    ]:
        block(s, x, 330, 430, 300, t, d, c)
    arrow(s, 515, 480, 70, 0)
    arrow(s, 1015, 480, 70, 0)
    label(
        s,
        85,
        695,
        1430,
        75,
        "一条规律记录应同时回答：观察到了什么？哪些证据冲突？下一轮验证什么？",
        30,
        ACC,
    )
    slides.append(s)

    s = page(
        "boundaries",
        "数据与确认边界：探索可以反复，确认单独准入",
        "从输入字段到保留样本，分清可用于选择的信息和可用于确认的证据。",
        "S05",
        [
            "数据面板将历史字段与未来标签分开，并保留缺失和隔离状态。",
            "A 段内部训练与后续探索分段不等于 B/H 独立确认。",
            "B/H 读取前检查准入，采用冻结批次校正；fast 不授予正式 PASS。",
        ],
    )
    for x, t, d, c in [
        (
            85,
            "A / 探索段",
            "机制提案与候选筛查\n训练条件与方向选择\n后续探索诊断",
            "允许生成新的研究假设",
        ),
        (
            585,
            "B / 确认段",
            "冻结批次准入\n必要断言与联合判定\nHolm 多重比较校正",
            "确认入口独立审计",
        ),
        (
            1085,
            "H / 保留段",
            "单独的保留样本入口\n访问事实与有效性记录\n按协议继续确认",
            "不能回流探索调参",
        ),
    ]:
        block(s, x, 330, 430, 285, t, d, c)
    arrow(s, 515, 472, 70, 0)
    arrow(s, 1015, 472, 70, 0)
    block(
        s,
        85,
        680,
        1430,
        105,
        "输入契约",
        "历史字段与收益标签分离 · purge 时间间隔 · 日历资格掩码 · 异常字段保持缺失或隔离",
    )
    slides.append(s)

    s = page(
        "recovery",
        "长任务可靠性：冻结、提交、检查点与恢复",
        "研究运行数小时后中断，也需要知道哪些测量已经完成、哪些仍未完成。",
        "S04",
        [
            "测量先持久化，再做归纳后处理，归纳失败可以恢复。",
            "恢复前核对代码、数据、环境和统计配置。",
            "暂停和停止在安全检查点边界生效。",
            "指纹与审计支持一致性核查，不等于不可篡改认证。",
        ],
    )
    for j, (t, d, c) in enumerate(
        [
            ("冻结身份", "代码 / 数据 / 配置\n候选与运行环境指纹", "audit.py · pipeline.py"),
            ("测量提交", "结果先落盘\n保留完整测量与耗时", "pipeline.py"),
            ("检查点", "状态、预算与队列\n区分完成与未完成", "checkpoint.json"),
            ("安全控制", "暂停 / 停止请求\n检查点边界生效", "control.json"),
            ("恢复核验", "一致性检查\n后处理可审计恢复", "recover_reconciler.py"),
            ("产物读取", "接口投影真实状态\n报告与研究日志导出", "dashboard_server.py"),
        ]
    ):
        block(s, 85 + (j % 3) * 500, 285 + (j // 3) * 265, 430, 205, t, d, c)
    slides.append(s)

    s = page(
        "interfaces",
        "同一研究能力，提供三种使用入口",
        "研究引擎、轻量 SDK 和控制台职责明确，便于接入与复核。",
        "S05",
        [
            "CLI 驱动完整研究，适合批次运行。",
            "SDK 支持自有数据独立实验，不调用外部模型。",
            "控制台负责查看和任务管理，读取真实产物。",
        ],
    )
    for x, t, d, c in [
        (
            85,
            "Research Engine",
            "完整模型角色编排\n统计检验与递归队列\n组合研究与执行适配",
            "run_engine.py · composition/",
        ),
        (
            585,
            "Research SDK",
            "自有 CSV / Parquet\nCellSpec / ExperimentSpec\n训练选择与验证评估",
            "research_sdk/ · studio_api.py",
        ),
        (
            1085,
            "Control Panel",
            "二维 / 三维机制地图\n证据、谱系、日志与报告\n任务状态及操作入口",
            "React · FastAPI · server_jobs.py",
        ),
    ]:
        block(s, x, 320, 430, 330, t, d, c)
    label(
        s,
        85,
        712,
        1430,
        70,
        "试点对象：量化研究团队与金融工程实验室；先验证接入、复核和研究管理效率。",
        27,
        ACC,
    )
    slides.append(s)

    s = page(
        "contributions",
        "创新落在模块之间的协议与反馈",
        "机制约束 × 异质性演化 × 证据记忆，共同构成可审计的研究循环。",
        "S05",
        [
            "贡献一是机制语义和可执行合同之间的绑定。",
            "贡献二是训练局部线索和重新冻结子代之间的转换。",
            "贡献三是证据记忆和有界调度之间的反馈。",
            "这些是已实现的设计贡献；相对方法增益仍需同预算消融。",
        ],
    )
    for x, t, d, c in [
        (
            85,
            "机制 → 合同",
            "让模型的经济解释\n对应可执行表达式\n与明确的检验需求",
            "语义与计算连接",
        ),
        (
            585,
            "异质性 → 子代",
            "让局部条件和方向\n进入有谱系的新假设\n继续接受固定评估器检验",
            "发现与验证连接",
        ),
        (
            1085,
            "证据 → 记忆",
            "让支持、冲突与未知\n保留为后续研究输入\n同时保持确认入口独立",
            "实验与积累连接",
        ),
    ]:
        block(s, x, 320, 430, 310, t, d, c, accent=(x == 585))
    snapshot = json.loads(
        (ROOT / "docs/research/2026-09-09-results.json").read_text(encoding="utf-8")
    )
    label(
        s,
        85,
        700,
        1430,
        75,
        f"实现状态 / 2026-09-09：已归档 {len(snapshot['candidates'])} 个完成候选；研究原型可运行，独立确认尚未完成。",
        25,
        MUTED,
    )
    slides.append(s)

    s = page(
        "closing",
        "让研究可以继续，\n让证据可以追溯。",
        "AURORA / ARCHITECTURE FOR RECURSIVE RESEARCH",
        "S10",
        [
            "回到架构主线：提出、冻结、检验、演化、记录。",
            "下一步通过正式确认和同预算消融验证方法增益。",
            "感谢评审，进入架构与实现问答。",
        ],
    )
    label(s, 85, 330, 690, 215, "机制先行\n实验有界\n证据留痕", 62, ACC)
    for y, t, d in [
        (330, "01  验证统计有效性", "补齐安慰剂校准与独立确认"),
        (485, "02  验证方法增益", "同预算比较演化与记忆反馈"),
        (640, "03  验证使用价值", "自有数据试点与研究复核效率"),
    ]:
        label(s, 900, y, 615, 46, t, 30)
        label(s, 900, y + 61, 615, 60, d, 24, MUTED)
    slides.append(s)
    return slides


def html_elements(s: Slide) -> str:
    """将共享元素转为百分比 HTML 与几何 SVG，输入页面，返回不含外部依赖的片段。"""
    if s.get("figure"):
        return f'<img class="paper-figure" src="figures/{s["figure"]}.png" data-image-slot="paper-diagram-5x2" alt="{escape(s["title"])}">'
    pieces = []
    for e in s["elements"]:
        if e["kind"] == "arrow":
            x, y = e["x"], e["y"]
            endx, endy = x + e["dx"], y + e["dy"]
            dash = 'stroke-dasharray="8 6"' if e["dashed"] else ""
            pieces.append(
                f'<svg class="diagram-lines" viewBox="0 0 1600 900"><defs><marker id="a-{x}-{y}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#{ACC}"/></marker></defs><path d="M{x},{y} L{endx},{endy}" fill="none" stroke="#{ACC}" stroke-width="2" {dash} marker-end="url(#a-{x}-{y})"/></svg>'
            )
            continue
        style = f"left:{e['x'] / 16}%;top:{e['y'] / 9}%;width:{e['w'] / 16}%;height:{e['h'] / 9}%;"
        if e["kind"] == "box":
            pieces.append(f'<div class="module-bg" style="{style}background:#{e["color"]}"></div>')
        else:
            pieces.append(
                f'<div class="diagram-text" style="{style}font-size:{e["size"] / 16}vw;color:#{e["color"]}">{escape(e["text"]).replace(chr(10), "<br>")}</div>'
            )
    return "".join(pieces)


def web_deck(slides: list[Slide]) -> None:
    """注入模板并保留导航与讲者功能，输入页面列表，返回 None，按用户品牌覆盖主题。"""
    template = (ROOT / "docs/ppt/assets/template-swiss.html").read_text(encoding="utf-8")
    rendered = []
    for i, s in enumerate(slides):
        chrome = f'<div class="deck-brand">AURORA / SYSTEM ARCHITECTURE</div><div class="deck-number">{i + 1:02d} / {len(slides):02d}</div>'
        inner = (
            f'<img class="cover-image" src="images/01-cover.png" data-image-slot="user-cover-16x9" alt="AURORA 原始封面">'
            if i == 0
            else chrome
            + f'<h1 class="deck-title">{escape(s["title"]).replace(chr(10), "<br>")}</h1><p class="deck-subtitle">{escape(s["subtitle"])}</p>'
            + html_elements(s)
        )
        rendered.append(
            f'<section class="slide" data-layout="{s["layout"]}" data-slide-id="{s["id"]}"><div class="canvas-card diagram-page">{inner}</div></section>'
        )
    start = template.index('<div id="deck">') + len('<div id="deck">')
    end = template.index('<div id="nav">', start)
    template = template[:start] + "".join(rendered) + "</div>\n" + template[end:]
    notes = [
        dict(
            id=s["id"],
            title=s["title"],
            purpose=s["subtitle"],
            talk=s["notes"],
            transition=slides[i + 1]["title"] if i + 1 < len(slides) else "进入架构问答",
        )
        for i, s in enumerate(slides)
    ]
    template = re.sub(
        r"const SPEAKER_NOTES = \[[\s\S]*?\];",
        lambda _: "const SPEAKER_NOTES = " + json.dumps(notes, ensure_ascii=False) + ";",
        template,
        count=1,
    )
    template = re.sub(r"<link[^>]+(?:fonts.googleapis|fonts.gstatic)[^>]*>", "", template)
    template = re.sub(r'<script src="https://unpkg.com/lucide[^>]*></script>', "", template)
    template = template.replace(
        "<script>lucide.createIcons();</script>", "<script>window.lucide?.createIcons();</script>"
    )
    template = template.replace("[必填] 替换为 PPT 标题 · Deck Title", "AURORA · 项目架构")
    css = """
:root{--paper:#102B30;--paper-rgb:16,43,48;--ink:#E9F2E9;--ink-rgb:233,242,233;--accent:#72CBC0;--accent-rgb:114,203,192;--accent-on:#102B30;--grey-1:#173B40;--grey-2:#386064;--grey-3:#A7C3C5;--text-primary:#E9F2E9;--text-secondary:#A7C3C5;--text-helper:#A7C3C5;--border-subtle:#386064}
.diagram-page{padding:0!important;display:block!important;background:#102B30!important;position:relative!important;width:100vw!important;height:100vh!important;font-family:"Microsoft YaHei",sans-serif!important}
.diagram-page>*{position:absolute!important;margin:0!important;line-height:1.4;font-weight:400;z-index:auto!important}.module-bg{border:1px solid #386064}.diagram-text{white-space:normal;overflow:visible}.diagram-lines{inset:0;width:100%;height:100%;pointer-events:none}.deck-brand{left:5.3125%;top:4.5%;font-size:1vw;color:#A7C3C5;letter-spacing:.16em}.deck-number{right:5.3125%;top:4.5%;font-size:1vw;color:#A7C3C5}.deck-title{left:5.3125%;top:11.5%;width:89.375%;font-size:3.15vw;letter-spacing:-.04em;line-height:1.25!important}.deck-subtitle{left:5.3125%;top:22.2%;width:89.375%;font-size:1.43vw;color:#A7C3C5}.paper-figure{left:5.3125%;top:28.8889%;width:89.375%;height:63.5556%;object-fit:contain;background:white}.cover-image{inset:0;width:100%;height:100%;object-fit:contain}
section[data-slide-id="closing"] .deck-title{font-size:3.3vw;top:11%}section[data-slide-id="closing"] .deck-subtitle{top:29.4%;font-size:1vw;color:#72CBC0}
"""
    template = template.replace("</head>", "<style>" + css + "</style></head>")
    (OUT / "index.html").write_text(template, encoding="utf-8")


def ppt_text(
    slide: Any, x: int, y: int, w: int, h: int, value: str, size: int, color: str = FG
) -> None:
    """添加原生文本框；输入像素坐标与字号，返回 None，按 120 像素每英寸映射。"""
    frame = slide.shapes.add_textbox(
        Inches(x / 120), Inches(y / 120), Inches(w / 120), Inches(h / 120)
    ).text_frame
    frame.word_wrap = True
    frame.margin_top = frame.margin_bottom = frame.margin_left = frame.margin_right = 0
    for i, line in enumerate(value.split("\n")):
        p = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        p.text = line
        p.font.name = "Microsoft YaHei"
        p.font.size = Pt(size * 0.6)
        p.font.color.rgb = RGBColor.from_string(color)
        p.space_after = Pt(size * 0.2)


def powerpoint(slides: list[Slide]) -> None:
    """生成原生可编辑宽屏 PPTX；输入共享页面，返回 None，几何位置与网页保持一致。"""
    deck = Presentation()
    deck.slide_width = Inches(1600 / 120)
    deck.slide_height = Inches(900 / 120)
    for i, s in enumerate(slides):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor.from_string(BG)
        slide.notes_slide.notes_text_frame.text = "\n".join(s["notes"])
        if i == 0:
            slide.shapes.add_picture(
                str(OUT / "images/01-cover.png"),
                0,
                0,
                width=deck.slide_width,
                height=deck.slide_height,
            )
            continue
        ppt_text(slide, 85, 40, 1200, 30, "AURORA / SYSTEM ARCHITECTURE", 16, MUTED)
        ppt_text(slide, 1425, 40, 100, 30, f"{i + 1:02d} / {len(slides):02d}", 16, MUTED)
        ppt_text(slide, 85, 100, 1430, 160 if s["id"] == "closing" else 85, s["title"], 50)
        ppt_text(
            slide, 85, 252 if s["id"] == "closing" else 194, 1430, 45, s["subtitle"], 22, MUTED
        )
        if s.get("figure"):
            slide.shapes.add_picture(
                str(OUT / "figures" / f"{s['figure']}.png"),
                Inches(85 / 120),
                Inches(260 / 120),
                width=Inches(1430 / 120),
                height=Inches(572 / 120),
            )
            continue
        for e in s["elements"]:
            if e["kind"] == "text":
                ppt_text(slide, e["x"], e["y"], e["w"], e["h"], e["text"], e["size"], e["color"])
            elif e["kind"] == "box":
                shape = slide.shapes.add_shape(
                    MSO_SHAPE.RECTANGLE,
                    Inches(e["x"] / 120),
                    Inches(e["y"] / 120),
                    Inches(e["w"] / 120),
                    Inches(e["h"] / 120),
                )
                shape.fill.solid()
                shape.fill.fore_color.rgb = RGBColor.from_string(e["color"])
                shape.line.color.rgb = RGBColor.from_string(BORDER)
            else:
                from pptx.oxml.xmlchemy import OxmlElement

                shape = slide.shapes.add_connector(
                    MSO_CONNECTOR.STRAIGHT,
                    Inches(e["x"] / 120),
                    Inches(e["y"] / 120),
                    Inches((e["x"] + e["dx"]) / 120),
                    Inches((e["y"] + e["dy"]) / 120),
                )
                shape.line.color.rgb = RGBColor.from_string(ACC)
                shape.line.width = Pt(1.2)
                head = OxmlElement("a:tailEnd")
                head.set("type", "triangle")
                shape.line._get_or_add_ln().append(head)
    for name in ["AURORA_项目架构.pptx", "AURORA_论文图示版.pptx", "AURORA_比赛简版.pptx"]:
        deck.save(OUT / name)
    assert len(Presentation(OUT / "AURORA_项目架构.pptx").slides) == len(slides)


def main() -> None:
    """从仓库生成架构稿及提纲，无参数，返回 None，复用已有封面与 skill 运行时。"""
    OUT.mkdir(parents=True, exist_ok=True)
    slides = content()
    figures = {
        "architecture": "01-system-architecture",
        "roles": "02-role-firewall",
        "contract": "03-contract-compilation",
        "evolution": "04-bounded-evolution",
    }
    for slide in slides:
        if slide["id"] in figures:
            slide["figure"] = figures[slide["id"]]
            if not (OUT / "figures" / f"{slide['figure']}.png").is_file():
                raise FileNotFoundError("请先执行 scripts/build_paper_diagrams.py")
    web_deck(slides)
    powerpoint(slides)
    (OUT / "slides.json").write_text(
        json.dumps(slides, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    plan = [
        "# AURORA 架构演示稿",
        "",
        "用户已指定封面品牌风格；本版重点改为架构、模块关系和信息流。",
        "",
        "| 页 | 页面 | 版式参考 | 演讲目的 |",
        "|---|---|---|---|",
    ]
    plan += [
        f"| {i + 1} | {s['title'].replace(chr(10), ' ')} | {s['layout']} | {s['subtitle']} |"
        for i, s in enumerate(slides)
    ]
    plan += [
        "",
        "架构图采用统一的深青底、薄荷绿主链和细线反馈。用户要求突出架构，因此模块图按实际关系适配，不将登记版式机械套成三层同心圆。原始封面保留。四个关键架构页嵌入论文式图示，独立 PNG/PDF/SVG 位于 figures/；这些图示在 PowerPoint 中为图片，其他页仍保留原生文字和模块。原生模块版另存为 AURORA_原生模块编辑版.pptx。",
        "",
        "网页：方向键翻页，ESC 总览，P 演讲者模式。PowerPoint：打开 AURORA_项目架构.pptx。",
        "生成：项目 Python 先执行 scripts/build_paper_diagrams.py，再执行 scripts/build_competition_deck.py；需 python-pptx。模板位于 docs/ppt/assets/template-swiss.html。",
    ]
    (OUT / "README.md").write_text("\n".join(plan), encoding="utf-8")
    print(f"Generated architecture deck: {len(slides)} slides")


if __name__ == "__main__":
    main()
