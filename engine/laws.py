"""规律账本管线：只允许可求值 scope、确认状态和证据引用完整的市场规律落盘。"""

import ast
from pathlib import Path
from typing import Any

import yaml


def validate_scope(scope: str, fields: set[str]) -> None:
    """验证账本谓词只使用字段、比较和布尔运算；输入表达式/字段白名单，非法即拒绝。"""
    tree = ast.parse(scope, mode="eval")
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in fields:
            raise ValueError(f"规律 scope 使用未知字段: {node.id}")
        if not isinstance(node, (ast.Expression, ast.BoolOp, ast.Compare, ast.Name, ast.Constant,
                                 ast.And, ast.Or, ast.Not, ast.UnaryOp, ast.Load, ast.Lt, ast.LtE,
                                 ast.Gt, ast.GtE, ast.Eq, ast.NotEq, ast.In, ast.NotIn, ast.List, ast.Tuple)):
            raise ValueError("规律 scope 含不可执行语法")


def write_law(
    root: Path, law_id: str, kind: str, claim: str, scope: str, evidence: list[str],
    reopen: str, confirmed: bool = False, scope_negative: str | None = None,
) -> dict[str, Any]:
    """校验并原子写入规律条目；输入账本字段，返回规范字典，确认需有 B 证据。"""
    if kind not in {"度量层", "传导层", "条件层", "边界层"} or not claim.strip() or not evidence or not reopen.strip():
        raise ValueError("规律类型、主张、证据、重开条件不能为空")
    validate_scope(scope, {"in_pool", "market_cap_pct", "realized_vol_pct", "is_index_member",
                           "turnover_today_pct", "avg_trade_size_pct", "auction_spread_pct"})
    if confirmed and not any("B" in item or "H" in item for item in evidence):
        raise ValueError("confirmed=true 必须引用确认段 B 或封存段 H 证据")
    law = {"id": law_id, "kind": kind, "claim": claim, "scope_predicate": scope,
           "scope_negative": scope_negative, "confirmed": confirmed, "evidence": evidence,
           "reopen": reopen, "model_terms": []}
    path = root / "law.yaml"
    existing = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else []
    if existing is None:
        existing = []
    if any(item.get("id") == law_id for item in existing):
        raise ValueError(f"规律 ID 已存在: {law_id}")
    existing.append(law)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(yaml.safe_dump(existing, allow_unicode=True, sort_keys=False), encoding="utf-8")
    temporary.replace(path)
    return law
