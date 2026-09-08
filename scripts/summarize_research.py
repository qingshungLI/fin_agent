"""结果汇总管线：读取已落盘结构，提取登记主周期指标，输出带资格边界的 Markdown。

只读取研究目录中的结果，不加载行情或确认段；运行中也可生成部分结果快照。
"""

import argparse
import json
from pathlib import Path
from typing import Any


def number(value: Any) -> str:
    """格式化可缺失的指标。

    Args:
        value: JSON 数值或 None。
    Returns:
        str: 六位小数或缺失标记，假设输入已经通过产物校验。
    """
    return "—" if value is None else f"{value:.6f}"


def summarize(folder: Path) -> str:
    """生成批次结果表和阻塞原因。

    Args:
        folder: 存在 checkpoint.json 的研究目录。
    Returns:
        str: Markdown；未完成批次显式标注当前完成数量。
    """
    state = json.loads((folder / "checkpoint.json").read_text(encoding="utf-8"))
    rows = [json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(folder.glob("S-*/result.json"))]
    lines = [f"# 研究批次 {folder.name}", "", f"状态：{state['status']}；完成结构：{len(rows)}。",
             "本表是 A 段研究证据，正 IC 不等于正式合格因子。", "",
             "| 结构 | 主周期 | IC | 安慰剂 | 成本后最高组超额 | A 分段一致 | 秒 |",
             "|---|---:|---:|---|---:|---|---:|"]
    for row in rows:
        horizon = row["structure"]["primary_horizon"]
        curve = next(item for item in row["measurement"]["curves"]
                     if item["expression"] == 1 and item["horizon"] == horizon)
        lines.append(f"| {row['name']} | {horizon} | {number(curve['mean'])} | "
                     f"{row['blades']['placebo']['state']} | "
                     f"{number(row['cost']['net_top_excess_mean'])} | "
                     f"{row['stability']['consistent']} | {row['seconds']:.1f} |")
    for row in rows:
        lines.extend(["", f"## {row['id']}", "",
                      "晋级阻塞：" + "; ".join(row["confirmation"]["reasons"])])
        placebo = row["blades"]["placebo"]
        for test in placebo.get("tests", []):
            lines.append(f"- {test['kind']}: {test['state']}, p={number(test.get('p'))}, "
                         f"频谱误差={number(test.get('spectral_error'))}")
        if placebo.get("reason"):
            lines.append("- 安慰剂说明：" + placebo["reason"])
    return "\n".join(lines) + "\n"


def main() -> int:
    """读取 CLI 目录参数并输出汇总。

    Returns:
        int: 成功返回 0；输入目录或 JSON 损坏时明确抛错。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = summarize(args.folder)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
