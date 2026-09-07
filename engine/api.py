"""服务管线：为前端提供只读研究状态、地图、数据检查和审计事件。

API 不在请求线程读取全量行情；正式运行通过 CLI 生成 artifacts，再由此服务展示冻结产物。
"""

from pathlib import Path
from typing import Any
import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from engine.audit import AuditStore
from engine.catalog import build_map

ARTIFACT_ROOT = Path("artifacts")
app = FastAPI(title="AutoAlpha Research API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["GET"], allow_headers=["*"])


def read_json(name: str, default: Any) -> Any:
    """读取产物 JSON；输入白名单文件名，缺失返回默认值且不伪造正式结论。"""
    path = ARTIFACT_ROOT / name
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"产物损坏: {name}") from exc


@app.get("/api/health")
def health() -> dict[str, Any]:
    """返回服务与产物状态；无参数，供前端启动检查。"""
    return {"ok": True, "artifacts": ARTIFACT_ROOT.exists()}


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    """返回工作台总览；无参数，只公开已落盘指标和严格阻断状态。"""
    result = read_json("overview.json", {})
    result.setdefault("map", build_map())
    result.setdefault("status", "NOT_RUN")
    result.setdefault("message", "尚未运行研究批次；正式数据检查失败时不会生成 PASS")
    return result


@app.get("/api/structures")
def structures() -> list[dict[str, Any]]:
    """返回结构卡列表；无参数，不读取原始收益数据。"""
    return read_json("structures.json", [])


@app.get("/api/audit")
def audit() -> dict[str, Any]:
    """验证并返回审计链；无参数，链损坏返回 HTTP 500。"""
    store = AuditStore(ARTIFACT_ROOT)
    try:
        return store.verify()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/structures/{structure_id}")
def structure_detail(structure_id: str) -> dict[str, Any]:
    """返回指定结构的冻结档案和测量结果；输入 ID，找不到返回 404。"""
    rows = structures()
    for row in rows:
        if row.get("id") == structure_id:
            return row
    raise HTTPException(status_code=404, detail="结构不存在")
