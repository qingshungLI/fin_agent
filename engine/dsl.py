"""表达式管线：解析受限 AST，检查量纲、窗口和字段可得性，再在对齐面板上求值。

不执行 Python eval；只允许注册字段及白名单函数。除零/无效对数保留 NaN，条件外无意见。
"""

import ast
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from engine.data import industry_mean

DIMENSIONS = {"open": 1, "close": 1, "high": 1, "low": 1, "adj_close": 1,
              "prev_close": 1, "market_cap": 1, "avg_trade_size": 1,
              "total_turnover": 1, "auction_amount": 1, "amihud": -1}
FORBIDDEN = ("raw_", "net_", "industry_resid_", "market_excess_", "future", "label")
ARITY = {"add": 2, "sub": 2, "mul": 2, "div": 2, "log": 1, "abs": 1,
         "sign": 1, "neg": 1, "lag": 2, "diff": 2, "ts_mean": 2, "ts_std": 2,
         "ts_min": 2, "ts_max": 2, "ts_z": 2, "ts_rank": 2, "xs_rank": 1,
         "xs_z": 1, "industry_mean": 1, "gate": 2, "where": 3}


@dataclass(frozen=True)
class CompiledExpression:
    """保存审查后的 AST；输入表达式、量纲和依赖，假设编译器完成验证。"""

    expression: str
    tree: ast.Expression
    scale_exponent: int
    dependencies: tuple[str, ...]


def compile_expression(
    expression: str, field_names: set[str], cuts: dict[str, dict[str, Any]] | None = None,
) -> CompiledExpression:
    """验证 DSL 并返回编译对象；输入白名单和冻结切点，拒绝任意属性/下标/代码。"""
    if len(expression) > 2000:
        raise ValueError("表达式超过 2000 字符")
    tree = ast.parse(expression, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 150:
        raise ValueError("表达式 AST 超过 150 节点")
    dependencies: set[str] = set()
    cuts = cuts or {}

    def dimension(node: ast.AST) -> int:
        """递归推导节点量纲；输入 AST，返回价格尺度指数，未知节点拒绝。"""
        if isinstance(node, ast.Name):
            if node.id not in field_names or node.id.startswith(FORBIDDEN):
                raise ValueError(f"未注册或未来字段: {node.id}")
            dependencies.add(node.id)
            return DIMENSIONS.get(node.id, 0)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float, bool):
            if not np.isfinite(node.value):
                raise ValueError("常数必须有限")
            return 0
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            if not isinstance(node.ops[0], (ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq)):
                raise ValueError("不支持该比较运算")
            if dimension(node.left) != dimension(node.comparators[0]):
                raise ValueError("比较两侧量纲不一致")
            return 0
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            if any(dimension(value) != 0 for value in node.values):
                raise ValueError("条件必须无量纲")
            return 0
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            dimension(node.operand)
            return 0
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            raise ValueError("只允许注册字段、比较和 DSL 函数")
        name = node.func.id
        if name not in ARITY or len(node.args) != ARITY[name] or node.keywords:
            raise ValueError(f"不支持的算子或参数数量: {name}")
        if name == "gate":
            cut_node = node.args[1]
            if not isinstance(cut_node, ast.Constant) or cut_node.value not in cuts:
                raise ValueError("gate 必须引用冻结切点 ID")
            dimension(node.args[0])
            return 0
        first = dimension(node.args[0])
        if name.startswith("ts_") or name in ("lag", "diff"):
            window = node.args[1]
            if not isinstance(window, ast.Constant) or type(window.value) is not int or not 1 <= window.value <= 252:
                raise ValueError("历史窗口必须为 1..252 的整数")
            if name in ("ts_std", "ts_z") and window.value < 2:
                raise ValueError("标准差至少需要两期")
            return 0 if name in ("ts_z", "ts_rank") else first
        if name in ("xs_z", "xs_rank", "sign", "log"):
            return 0
        if name in ("neg", "abs", "industry_mean"):
            return first
        second = dimension(node.args[1])
        if name in ("add", "sub") and first != second:
            raise ValueError("加减两侧量纲不一致")
        if name == "where":
            third = dimension(node.args[2])
            if first != 0 or second != third:
                raise ValueError("where 条件或分支量纲错误")
            return second
        return first + second if name == "mul" else first - second if name == "div" else first

    scale = dimension(tree.body)
    return CompiledExpression(expression, tree, scale, tuple(sorted(dependencies)))


def evaluate(
    expression: str, fields: dict[str, pd.DataFrame],
    cuts: dict[str, dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """计算已验证表达式；输入面板和切点，返回同形矩阵，不允许未来字段参与。"""
    cuts = cuts or {}
    compiled = compile_expression(expression, set(fields), cuts)
    prototype = next(iter(fields.values()))

    def visit(node: ast.AST) -> Any:
        """求值单个受限节点；参数为 AST，返回标量或矩阵，编译已验证节点类型。"""
        if isinstance(node, ast.Name):
            return fields[node.id]
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.UnaryOp):
            return ~visit(node.operand).astype(bool)
        if isinstance(node, ast.BoolOp):
            items = [visit(item) for item in node.values]
            value = items[0]
            for item in items[1:]:
                value = value & item if isinstance(node.op, ast.And) else value | item
            return value
        if isinstance(node, ast.Compare):
            left, right = visit(node.left), visit(node.comparators[0])
            methods = {ast.Lt: "lt", ast.LtE: "le", ast.Gt: "gt", ast.GtE: "ge", ast.Eq: "eq", ast.NotEq: "ne"}
            return getattr(left, methods[type(node.ops[0])])(right)
        name = node.func.id
        args = [visit(arg) for arg in node.args]
        x = args[0]
        if name == "gate":
            cut = cuts[args[1]]
            condition = x.ge(cut["value"]) if cut["side"] == "high" else x.le(cut["value"])
            return condition.astype(float).where(x.notna())
        if name == "where":
            return pd.DataFrame(np.where(x, args[1], args[2]), index=prototype.index, columns=prototype.columns)
        if name == "lag":
            return x.shift(args[1])
        if name == "diff":
            return x.diff(args[1])
        if name.startswith("ts_"):
            window = x.rolling(args[1], min_periods=args[1])
            if name == "ts_z":
                return (x - window.mean()) / window.std().replace(0, np.nan)
            if name == "ts_rank":
                return window.rank(pct=True)
            return getattr(window, name[3:])()
        if name == "xs_rank":
            return x.where(fields.get("in_pool", x.notna())).rank(axis=1, pct=True, method="average")
        if name == "xs_z":
            return x.sub(x.mean(axis=1), axis=0).div(x.std(axis=1).replace(0, np.nan), axis=0)
        if name == "industry_mean":
            return industry_mean(x, fields["industry"])
        if name == "log":
            return np.log(x.where(x > 0))
        if name in ("neg", "abs", "sign"):
            return -x if name == "neg" else abs(x) if name == "abs" else np.sign(x)
        y = args[1]
        if name == "div":
            denominator = y.replace(0, np.nan) if isinstance(y, pd.DataFrame) else (np.nan if y == 0 else y)
            return x / denominator
        return x + y if name == "add" else x - y if name == "sub" else x * y

    output = visit(compiled.tree.body)
    if not isinstance(output, pd.DataFrame):
        output = pd.DataFrame(output, index=prototype.index, columns=prototype.columns)
    return output.replace([np.inf, -np.inf], np.nan)
