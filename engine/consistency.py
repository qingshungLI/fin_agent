"""一致性管线：置信边构成符号图，BFS 定位受挫圈，整数规划计算最小删边代价。

同一个图内核服务于结构、表达式、时间块、词表与账本；图平衡不允许翻转冻结信号。
"""

from collections import deque
from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp


def balance_check(nodes: list[str], edges: list[dict[str, Any]]) -> dict[str, Any]:
    """检测符号图平衡及受挫圈；输入带符号/权重的边，返回二分、圈与删边代价。"""
    if len(nodes) != len(set(nodes)):
        raise ValueError("图节点重复")
    adjacency: dict[str, list[tuple[str, int]]] = {node: [] for node in nodes}
    active = []
    seen = set()
    for edge in edges:
        a, b, sign = edge["source"], edge["target"], edge["sign"]
        if a not in adjacency or b not in adjacency or a == b:
            raise ValueError("边含未知节点或自环")
        pair = tuple(sorted((a, b)))
        if pair in seen:
            raise ValueError("图中存在重复边")
        seen.add(pair)
        if sign is None:
            continue
        if sign not in (-1, 1) or edge.get("weight", 1) < 0:
            raise ValueError("边符号或权重不合法")
        adjacency[a].append((b, sign))
        adjacency[b].append((a, sign))
        active.append({**edge, "weight": edge.get("weight", 1.0)})
    colors: dict[str, int] = {}
    parent: dict[str, str | None] = {}
    cycles = []
    unique_cycles = set()
    for root in nodes:
        if root in colors:
            continue
        colors[root], parent[root] = 1, None
        queue = deque([root])
        while queue:
            a = queue.popleft()
            for b, sign in adjacency[a]:
                if b not in colors:
                    colors[b], parent[b] = colors[a] * sign, a
                    queue.append(b)
                elif colors[b] != colors[a] * sign:
                    path_a, path_b = [a], [b]
                    while parent[path_a[-1]] is not None:
                        path_a.append(parent[path_a[-1]])
                    while parent[path_b[-1]] is not None:
                        path_b.append(parent[path_b[-1]])
                    common = next(node for node in path_a if node in path_b)
                    cycle = path_a[:path_a.index(common) + 1] + list(reversed(path_b[:path_b.index(common)]))
                    key = tuple(sorted(cycle))
                    if key not in unique_cycles:
                        unique_cycles.add(key)
                        cycles.append(cycle)
    cost, exact = 0.0, True
    if cycles:
        if len(nodes) <= 200:
            n, m = len(nodes), len(active)
            objective = np.r_[np.zeros(n), [edge["weight"] for edge in active]]
            rows, lower = [], []
            for j, edge in enumerate(active):
                a, b = nodes.index(edge["source"]), nodes.index(edge["target"])
                for direction in (-1, 1):
                    row = np.zeros(n + m)
                    row[n + j] = 1
                    if edge["sign"] == 1:
                        row[a], row[b] = direction, -direction
                        lower.append(0)
                    else:
                        row[a], row[b] = direction, direction
                        lower.append(1 if direction == 1 else -1)
                    rows.append(row)
            solution = milp(objective, integrality=np.ones(n + m), bounds=Bounds(0, 1),
                            constraints=LinearConstraint(np.asarray(rows), lower, np.inf),
                            options={"time_limit": 30})
            if not solution.success:
                raise RuntimeError("符号图整数规划未收敛，不能冒充精确受挫指数")
            cost = float(solution.fun)
        else:
            exact = False
            cost = float(sum(edge["weight"] for edge in active
                             if colors[edge["target"]] != colors[edge["source"]] * edge["sign"]))
    return {"balanced": not cycles, "bipartition": colors, "cycles": cycles,
            "frustration_index": cost, "exact": exact, "nodes": nodes, "edges": active}


def confidence_edge(source: str, target: str, lower: float, upper: float) -> dict[str, Any]:
    """把置信区间转换为可信符号边；输入端点与区间，跨零时返回未知边。"""
    if lower > upper or not np.isfinite([lower, upper]).all():
        raise ValueError("置信区间无效")
    return {"source": source, "target": target, "sign": 1 if lower > 0 else -1 if upper < 0 else None,
            "weight": min(abs(lower), abs(upper)) if lower * upper > 0 else 0}


def consistency_views(library: list[dict[str, Any]]) -> dict[str, Any]:
    """构造表达式/时间/词表一致性视图；输入已测量档案，返回诊断，不根据图翻转方向。"""
    views = {}
    for record in library:
        curves = [row for row in record.get("measurement", {}).get("curves", []) if row["horizon"] == 5]
        nodes = [f"E{row['expression']}" for row in curves]
        signs = [1 if row["ci_low"] is not None and row["ci_low"] > 0 else
                 -1 if row["ci_high"] is not None and row["ci_high"] < 0 else None for row in curves]
        edges = [{"source": nodes[i], "target": nodes[j],
                  "sign": signs[i] * signs[j] if signs[i] and signs[j] else None, "weight": 1}
                 for i in range(len(nodes)) for j in range(i + 1, len(nodes))]
        views[record["id"]] = {**balance_check(nodes, edges),
                               "same_frozen_direction": len(signs) == 3 and all(sign == 1 for sign in signs),
                               "note": "乘积符号图只描述相对方向；同号必须独立检查"}
    return views
